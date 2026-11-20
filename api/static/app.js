// Jaden Konekté — tableau de bord (JavaScript sans framework)
"use strict";

const API = "/api/v1";
const SEUIL_DEFAUT = 25;            // seuil affiché quand la parcelle n'a pas de règle
const DELAI_CONFIRMATION_MS = 35000; // un peu plus que les 30 s du serveur

const etat = {
  jeton: sessionStorage.getItem("jeton"),
  parcelle: null,
  flux: null,               // AbortController du flux SSE en cours
  commandeEnAttente: null,  // { id, minuteur }
  periode: "24h",
  graphique: null,
  regle: null,              // règle d'arrosage de la parcelle (ou null)
  seuil: SEUIL_DEFAUT,
};

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------------------
// Appels à l'API
// ---------------------------------------------------------------------------

async function api(chemin, options = {}) {
  const reponse = await fetch(API + chemin, {
    ...options,
    headers: {
      // Pour un envoi de fichier (FormData), le navigateur fixe lui-même le Content-Type multipart
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(etat.jeton ? { Authorization: `Bearer ${etat.jeton}` } : {}),
      ...options.headers,
    },
  });
  if (reponse.status === 401 && etat.jeton) {
    deconnecter("Votre session a expiré : reconnectez-vous.");
    throw new Error("non authentifié");
  }
  const corps = await reponse.json().catch(() => null);
  if (!reponse.ok) {
    // Les erreurs de l'API sont au format Problem Details : on affiche "detail"
    throw new Error(corps?.detail || `Erreur ${reponse.status}`);
  }
  return corps;
}

// ---------------------------------------------------------------------------
// Connexion
// ---------------------------------------------------------------------------

$("form-connexion").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("erreur-connexion").textContent = "";
  try {
    const jeton = await api("/jetons", {
      method: "POST",
      body: JSON.stringify({ courriel: $("courriel").value, mot_de_passe: $("mot-de-passe").value }),
    });
    etat.jeton = jeton.access_token;
    sessionStorage.setItem("jeton", etat.jeton);
    await ouvrirTableau();
  } catch (err) {
    $("erreur-connexion").textContent = err.message;
  }
});

$("deconnexion").addEventListener("click", () => deconnecter());

function deconnecter(message = "") {
  etat.flux?.abort();
  etat.jeton = null;
  sessionStorage.removeItem("jeton");
  $("ecran-tableau").hidden = true;
  $("ecran-connexion").hidden = false;
  $("erreur-connexion").textContent = message;
}

// ---------------------------------------------------------------------------
// Parcelles
// ---------------------------------------------------------------------------

async function ouvrirTableau() {
  const page = await api("/parcelles?taille=100");
  $("ecran-connexion").hidden = true;
  $("ecran-tableau").hidden = false;

  const nav = $("parcelles");
  nav.replaceChildren();
  if (page.elements.length === 0) {
    nav.textContent = "Aucune parcelle n'est rattachée à votre compte.";
    return;
  }
  for (const p of page.elements) {
    const bouton = document.createElement("button");
    bouton.textContent = `${p.nom} (${p.culture})`;
    bouton.setAttribute("role", "tab");
    bouton.dataset.id = p.id;
    bouton.addEventListener("click", () => choisirParcelle(p.id));
    nav.append(bouton);
  }
  choisirParcelle(page.elements[0].id);
  chargerDiagnostics();
}

function choisirParcelle(id) {
  etat.parcelle = id;
  for (const b of $("parcelles").children) {
    b.setAttribute("aria-selected", String(Number(b.dataset.id) === id));
  }
  annulerAttente();
  $("vanne-message").textContent = "";
  chargerRegle(id);
  ecouterFlux(id);
  chargerHistorique();
}

// ---------------------------------------------------------------------------
// Flux temps réel (SSE)
// fetch() plutôt qu'EventSource : EventSource ne permet pas d'envoyer l'en-tête
// Authorization, et mettre le jeton dans l'URL l'exposerait dans les journaux.
// ---------------------------------------------------------------------------

async function ecouterFlux(id) {
  etat.flux?.abort();
  const controle = new AbortController();
  etat.flux = controle;

  try {
    const reponse = await fetch(`${API}/parcelles/${id}/flux`, {
      headers: { Authorization: `Bearer ${etat.jeton}` },
      signal: controle.signal,
    });
    if (reponse.status === 401) return deconnecter("Votre session a expiré : reconnectez-vous.");
    if (!reponse.ok) throw new Error(`flux ${reponse.status}`);

    const lecteur = reponse.body.pipeThrough(new TextDecoderStream()).getReader();
    let tampon = "";
    for (;;) {
      const { value, done } = await lecteur.read();
      if (done) break;
      tampon += value;
      // Un événement SSE se termine par une ligne vide
      let fin;
      while ((fin = tampon.indexOf("\n\n")) !== -1) {
        traiterEvenement(tampon.slice(0, fin));
        tampon = tampon.slice(fin + 2);
      }
    }
  } catch (err) {
    if (controle.signal.aborted) return;   // changement de parcelle ou déconnexion
  }
  // Connexion coupée (serveur redémarré, réseau…) : on se reconnecte après 3 s
  if (!controle.signal.aborted) setTimeout(() => ecouterFlux(id), 3000);
}

function traiterEvenement(bloc) {
  let type = "message";
  let donnees = "";
  for (const ligne of bloc.split("\n")) {
    if (ligne.startsWith("event:")) type = ligne.slice(6).trim();
    else if (ligne.startsWith("data:")) donnees += ligne.slice(5).trim();
  }
  if (type === "etat" && donnees) afficherEtat(JSON.parse(donnees));
}

// ---------------------------------------------------------------------------
// Affichage de l'état
// ---------------------------------------------------------------------------

const format = new Intl.DateTimeFormat("fr-FR", { dateStyle: "short", timeStyle: "short" });
const nombre = (v, decimales = 1) =>
  v.toLocaleString("fr-FR", { maximumFractionDigits: decimales });

function afficherEtat({ mesures, vanne }) {
  // Humidité du sol : la colonne se remplit d'eau
  const h = mesures.humidite;
  $("humidite").textContent = h ? nombre(h.valeur) : "–";
  $("humidite-ts").textContent = h ? `Mesure du ${format.format(new Date(h.ts))}` : "Pas encore de mesure valide";
  // Capteur en panne : la valeur affichée est la dernière fiable, et la règle n'arrose pas
  const panne = !!h && h.fiable === false;
  $("capteur-panne").hidden = !panne;
  document.querySelector(".sol").classList.toggle("panne", panne);
  $("eau").style.height = h ? `${Math.min(100, Math.max(0, h.valeur))}%` : "0";
  document.querySelector(".sol").classList.toggle("sec", !!h && h.valeur < etat.seuil);

  // Autres relevés
  $("temperature").textContent = mesures.temperature ? nombre(mesures.temperature.valeur) : "–";
  $("luminosite").textContent = mesures.luminosite ? nombre(mesures.luminosite.valeur, 0) : "–";
  $("intensite").textContent = mesures.intensite ? nombre(mesures.intensite.valeur) : "–";

  // Objet et vanne
  const statut = $("objet-statut");
  const enLigne = vanne?.en_ligne === true;
  statut.textContent = enLigne ? "Capteurs en ligne" : "Capteurs hors ligne";
  statut.className = `statut ${enLigne ? "en-ligne" : "hors-ligne"}`;

  const ouverte = vanne?.etat === "ouverte";
  $("vanne-etat").textContent = !vanne ? "Pas de vanne" : ouverte ? "Ouverte" : "Fermée";
  $("vanne-etat").className = `etat-vanne ${ouverte ? "ouverte" : ""}`;
  $("vanne-jusqua").textContent =
    ouverte && vanne.jusqua ? `Fermeture prévue le ${format.format(new Date(vanne.jusqua))}` : "";
  $("ouvrir").disabled = !enLigne;
  $("fermer").disabled = !enLigne;
  if (!enLigne && !etat.commandeEnAttente) {
    afficherMessage("Les capteurs de cette parcelle sont hors ligne : la vanne ne peut pas recevoir d'ordre.", "ko hors-ligne-info");
  } else if (enLigne && $("vanne-message").classList.contains("hors-ligne-info")) {
    afficherMessage("", "");
  }

  // La vanne a-t-elle confirmé la commande qu'on attend ?
  const attente = etat.commandeEnAttente;
  if (attente && vanne?.derniere_cmd === attente.id) {
    annulerAttente();
    afficherMessage(`Confirmé par la vanne : ${ouverte ? "ouverte" : "fermée"}.`, "ok");
  }
}

// ---------------------------------------------------------------------------
// Commande de la vanne
// ---------------------------------------------------------------------------

$("ouvrir").addEventListener("click", () => commander("ouvrir"));
$("fermer").addEventListener("click", () => commander("fermer"));

async function commander(action) {
  annulerAttente();
  const corps = { action };
  if (action === "ouvrir") corps.duree_s = Number($("duree").value);
  try {
    const commande = await api(`/parcelles/${etat.parcelle}/commandes`, {
      method: "POST",
      body: JSON.stringify(corps),
    });
    afficherMessage("Ordre envoyé, en attente de confirmation par la vanne…", "attente");
    etat.commandeEnAttente = {
      id: commande.id,
      minuteur: setTimeout(() => {
        etat.commandeEnAttente = null;
        afficherMessage("La vanne n'a pas confirmé l'ordre. Vérifiez qu'elle est en ligne.", "ko");
      }, DELAI_CONFIRMATION_MS),
    };
  } catch (err) {
    afficherMessage(err.message, "ko");
  }
}

function annulerAttente() {
  if (etat.commandeEnAttente) clearTimeout(etat.commandeEnAttente.minuteur);
  etat.commandeEnAttente = null;
}

function afficherMessage(texte, genre) {
  $("vanne-message").textContent = texte;
  $("vanne-message").className = `message ${genre}`;
}

// ---------------------------------------------------------------------------
// Règle d'arrosage automatique
// ---------------------------------------------------------------------------

async function chargerRegle(id) {
  try {
    etat.regle = await api(`/parcelles/${id}/regle`);
  } catch {
    etat.regle = null;   // 404 : pas de règle pour cette parcelle
  }
  if (id === etat.parcelle) afficherRegle();
}

function afficherRegle() {
  const r = etat.regle;
  const sol = r?.condition.et.find((c) => c.capteur === "sol/humidite");
  const pluie = r?.condition.et.find((c) => c.meteo === "pluie_6h");
  etat.seuil = sol ? sol.valeur : SEUIL_DEFAUT;
  $("seuil").style.bottom = `${etat.seuil}%`;
  $("seuil-valeur").textContent = nombre(etat.seuil);

  const bouton = $("regle-bascule");
  if (!r) {
    $("regle-texte").textContent = "Pas d'arrosage automatique sur cette parcelle.";
    bouton.hidden = true;
    return;
  }
  const minutes = Math.round(r.action.duree_s / 60);
  $("regle-texte").textContent = r.active
    ? `Arrosage automatique activé : ${minutes} min quand le sol passe sous ${nombre(etat.seuil)} %`
      + (pluie ? ` et que moins de ${nombre(pluie.valeur)} mm de pluie sont prévus.` : ".")
    : "Arrosage automatique désactivé.";
  bouton.textContent = r.active ? "Désactiver l'arrosage automatique" : "Activer l'arrosage automatique";
  bouton.hidden = false;

  // Pourquoi la règle arrose ou non : sa dernière décision, avec la pluie prévue (Open-Meteo)
  const decision = $("regle-decision");
  decision.replaceChildren();
  if (r.active && r.derniere_decision && r.derniere_evaluation) {
    const heure = new Intl.DateTimeFormat("fr-FR", { timeStyle: "short" }).format(new Date(r.derniere_evaluation));
    decision.append(
      Object.assign(document.createElement("strong"), { textContent: `Dernière vérification (${heure}) : ` }),
      document.createTextNode(r.derniere_decision),
    );
  }
}

// La règle est vérifiée toutes les 30 s par le service regles : on relit sa décision au même rythme
setInterval(() => { if (etat.jeton && etat.parcelle) chargerRegle(etat.parcelle); }, 30000);

$("regle-bascule").addEventListener("click", async () => {
  try {
    etat.regle = await api(`/parcelles/${etat.parcelle}/regle`, {
      method: "PATCH",
      body: JSON.stringify({ active: !etat.regle.active }),
    });
    afficherRegle();
  } catch (err) {
    $("regle-texte").textContent = err.message;
  }
});

// ---------------------------------------------------------------------------
// Historique (Chart.js)
// ---------------------------------------------------------------------------

$("grandeur").addEventListener("change", chargerHistorique);
for (const b of document.querySelectorAll(".bascule button")) {
  b.addEventListener("click", () => {
    etat.periode = b.dataset.periode;
    for (const autre of document.querySelectorAll(".bascule button")) {
      autre.setAttribute("aria-pressed", String(autre === b));
    }
    chargerHistorique();
  });
}
setInterval(() => etat.parcelle && chargerHistorique(), 60000);  // rafraîchi chaque minute

async function chargerHistorique() {
  const grandeur = $("grandeur").value;
  let serie;
  try {
    serie = await api(`/parcelles/${etat.parcelle}/mesures?grandeur=${grandeur}&periode=${etat.periode}`);
  } catch (err) {
    $("historique-message").textContent = err.message;
    return;
  }
  $("zone-graphique").hidden = serie.points.length === 0;
  $("historique-message").textContent = serie.points.length
    ? `Moyenne par tranche de ${serie.intervalle === "1 hour" ? "1 heure" : "6 heures"} ; la zone claire va du minimum au maximum.`
    : "Pas encore de mesures valides sur cette période.";

  const etiquette = (d) =>
    new Date(d).toLocaleString("fr-FR", etat.periode === "24h"
      ? { hour: "2-digit", minute: "2-digit" }
      : { weekday: "short", hour: "2-digit" });
  const donnees = {
    labels: serie.points.map((p) => etiquette(p.debut)),
    datasets: [
      { label: "Maximum", data: serie.points.map((p) => p.max), borderWidth: 0, pointRadius: 0,
        backgroundColor: "rgba(31, 111, 168, .15)", fill: "+1" },
      { label: "Minimum", data: serie.points.map((p) => p.min), borderWidth: 0, pointRadius: 0, fill: false },
      { label: `Moyenne (${serie.unite})`, data: serie.points.map((p) => p.moyenne),
        borderColor: "#1f6fa8", borderWidth: 2, pointRadius: 2, tension: .3, fill: false },
    ],
  };

  if (!window.Chart) {
    $("historique-message").textContent = "La bibliothèque de graphiques n'a pas pu être chargée.";
    return;
  }
  if (etat.graphique) {
    etat.graphique.data = donnees;
    etat.graphique.update();
  } else {
    etat.graphique = new Chart($("graphique"), {
      type: "line",
      data: donnees,
      options: {
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { display: false } },
        scales: { x: { grid: { display: false } }, y: { grid: { color: "#e3e9e0" } } },
      },
    });
  }
}

// ---------------------------------------------------------------------------
// Diagnostic par photo
// ---------------------------------------------------------------------------

const pourcent = (v) => `${Math.round(v * 100)} %`;
const SAINE = "Tomato___healthy";

$("photo").addEventListener("change", () => {
  const fichier = $("photo").files[0];
  $("analyser").disabled = !fichier;
  if (!fichier) return;
  const apercu = $("apercu");
  if (apercu.src) URL.revokeObjectURL(apercu.src);
  apercu.src = URL.createObjectURL(fichier);
  apercu.hidden = false;
  $("zone-texte").hidden = true;
});

$("form-diagnostic").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fichier = $("photo").files[0];
  if (!fichier) return;
  const donnees = new FormData();
  donnees.append("image", fichier);
  if (etat.parcelle) donnees.append("parcelle", etat.parcelle);

  $("analyser").disabled = true;
  $("analyser").textContent = "Analyse en cours…";
  try {
    const diag = await api("/diagnostics", { method: "POST", body: donnees });
    afficherDiagnostic(diag);
    chargerDiagnostics();
  } catch (err) {
    const zone = $("diag-resultat");
    zone.replaceChildren(paragraphe(err.message, "erreur"));
  } finally {
    $("analyser").disabled = false;
    $("analyser").textContent = "Analyser la photo";
  }
});

function paragraphe(texte, classe = "") {
  const p = document.createElement("p");
  p.textContent = texte;           // textContent : jamais de HTML injecté
  if (classe) p.className = classe;
  return p;
}

function afficherDiagnostic(diag) {
  const zone = $("diag-resultat");
  zone.replaceChildren();

  const maladie = paragraphe(diag.libelle, "diag-maladie" + (diag.classe === SAINE ? " saine" : ""));
  const jauge = document.createElement("div");
  jauge.className = "jauge" + (diag.fiable ? "" : " faible");
  jauge.setAttribute("role", "img");
  jauge.setAttribute("aria-label", `Confiance du modèle : ${pourcent(diag.score)}`);
  const barre = document.createElement("div");
  barre.style.width = pourcent(diag.score).replace(" ", "");
  jauge.append(barre);
  zone.append(maladie, jauge, paragraphe(`Confiance du modèle : ${pourcent(diag.score)}`, "discret"));

  if (!diag.fiable) {
    zone.append(paragraphe(
      "Le modèle n'est pas sûr de lui. La photo n'est peut-être pas une feuille de tomate, " +
      "ou elle est floue ou mal éclairée : reprenez une photo d'une seule feuille, de près.",
      "avertissement"));
  }

  const actions = document.createElement("div");
  actions.className = "diag-actions";
  // « Que faire ? » seulement pour une maladie détectée avec confiance et non démentie par l'exploitant
  if (diag.classe !== SAINE && diag.fiable && diag.confirme !== false) {
    actions.append(bouton("Que faire ?", "bouton-secondaire", () =>
      demanderAssistant(`Le diagnostic indique ${diag.libelle} sur mes tomates : que faire ?`)));
  }
  if (diag.confirme === null) {
    const oui = bouton("C'est bien ça", "bouton-principal", () => confirmer(diag.id, true));
    const non = bouton("Ce n'est pas ça", "bouton-secondaire", () => confirmer(diag.id, false));
    actions.append(oui, non);
  } else {
    actions.append(paragraphe(diag.confirme ? "Vous avez confirmé ce diagnostic." : "Vous avez indiqué que ce diagnostic est faux.", "discret"));
  }
  zone.append(actions);
}

function bouton(texte, classe, action) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = classe;
  b.textContent = texte;
  b.addEventListener("click", action);
  return b;
}

async function confirmer(id, confirme) {
  try {
    const diag = await api(`/diagnostics/${id}`, { method: "PATCH", body: JSON.stringify({ confirme }) });
    afficherDiagnostic(diag);
    chargerDiagnostics();
  } catch (err) {
    $("diag-resultat").append(paragraphe(err.message, "erreur"));
  }
}

// La photo demande le jeton : une balise <img src> ne peut pas l'envoyer,
// on la télécharge donc avec fetch() puis on l'affiche depuis la mémoire (blob).
async function chargerVignette(img, url) {
  try {
    const r = await fetch(url, { headers: { Authorization: `Bearer ${etat.jeton}` } });
    if (r.ok) img.src = URL.createObjectURL(await r.blob());
  } catch { /* vignette absente : sans gravité */ }
}

async function chargerDiagnostics() {
  const liste = $("diag-liste");
  try {
    const page = await api("/diagnostics?taille=5");
    for (const img of liste.querySelectorAll("img")) if (img.src) URL.revokeObjectURL(img.src);
    liste.replaceChildren();
    if (page.elements.length === 0) {
      liste.append(Object.assign(document.createElement("li"), { textContent: "Aucun diagnostic pour l'instant : envoyez une première photo." }));
      return;
    }
    for (const d of page.elements) {
      const li = document.createElement("li");
      const img = document.createElement("img");
      img.alt = "";
      chargerVignette(img, d.image_url);
      const texte = document.createElement("div");
      const titre = d.statut === "termine" ? d.libelle : "Analyse impossible";
      texte.append(
        Object.assign(document.createElement("strong"), { textContent: titre }),
        paragraphe(`${format.format(new Date(d.cree_le))}` + (d.score != null ? ` · ${pourcent(d.score)}` : ""), "discret"),
      );
      const avis = { true: "Confirmé", false: "Infirmé", null: "À confirmer" }[String(d.confirme)];
      li.append(img, texte, Object.assign(document.createElement("span"), { className: "avis", textContent: d.statut === "termine" ? avis : "" }));
      li.addEventListener("click", () => d.statut === "termine" && afficherDiagnostic(d));
      liste.append(li);
    }
  } catch (err) {
    liste.replaceChildren(Object.assign(document.createElement("li"), { textContent: err.message }));
  }
}

// ---------------------------------------------------------------------------
// Assistant agronome (réponse en streaming SSE, lue avec fetch comme le flux temps réel)
// ---------------------------------------------------------------------------

const NOMS_FICHES = {
  "01_tomate_culture.md": "Tomate : culture",
  "02_tomate_maladies.md": "Tomate : maladies et ravageurs",
  "03_igname.md": "Igname",
  "04_christophine.md": "Christophine",
  "05_irrigation_sol.md": "Arrosage et humidité du sol",
  "06_protocole_alerte.md": "Que faire en cas de maladie détectée ?",
};

$("form-assistant").addEventListener("submit", (e) => {
  e.preventDefault();
  demanderAssistant($("question").value.trim());
});
for (const b of $("exemples").children) {
  b.addEventListener("click", () => demanderAssistant(b.textContent));
}

async function demanderAssistant(question) {
  if (question.length < 3) return;
  $("question").value = question;
  $("titre-assistant").scrollIntoView({ behavior: "smooth", block: "start" });
  const zone = $("reponse-assistant"), texte = $("reponse-texte"), sources = $("reponse-sources");
  zone.hidden = false;
  zone.classList.remove("hors-fiches");
  texte.textContent = "L'assistant cherche dans les fiches…";
  texte.classList.add("attente");
  sources.replaceChildren();
  $("demander").disabled = true;

  let premier = true;
  try {
    const reponse = await fetch(API + "/assistant/questions", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${etat.jeton}` },
      body: JSON.stringify({ question }),
    });
    if (!reponse.ok) {
      const corps = await reponse.json().catch(() => null);
      throw new Error(corps?.detail || `Erreur ${reponse.status}`);
    }
    const lecteur = reponse.body.pipeThrough(new TextDecoderStream()).getReader();
    let tampon = "";
    for (;;) {
      const { value, done } = await lecteur.read();
      if (done) break;
      tampon += value;
      const blocs = tampon.split("\n\n");      // un événement SSE se termine par une ligne vide
      tampon = blocs.pop();
      for (const bloc of blocs) {
        const nom = bloc.match(/^event: (.*)$/m)?.[1];
        const donnees = bloc.match(/^data: (.*)$/m)?.[1];
        if (!donnees) continue;
        const d = JSON.parse(donnees);
        if (nom === "texte") {
          if (premier) { texte.textContent = ""; texte.classList.remove("attente"); premier = false; }
          texte.textContent += d.t;
        } else if (nom === "fin") {
          afficherSources(d);
        } else if (nom === "erreur") {
          throw new Error(d.detail);
        }
      }
    }
  } catch (err) {
    texte.classList.remove("attente");
    texte.textContent = err.message;
    zone.classList.add("hors-fiches");
  } finally {
    $("demander").disabled = false;
  }
}

function afficherSources({ hors_fiches, sources }) {
  const liste = $("reponse-sources");
  if (hors_fiches) {
    $("reponse-assistant").classList.add("hors-fiches");
    return;
  }
  for (const s of sources) {
    const li = document.createElement("li");
    li.append(
      Object.assign(document.createElement("strong"), { textContent: `[${s.numero}] ` }),
      document.createTextNode(`Fiche « ${NOMS_FICHES[s.source] || s.source} », section « ${s.section} »`),
    );
    liste.append(li);
  }
}

// ---------------------------------------------------------------------------
// Démarrage : si un jeton est déjà en mémoire, on va directement au tableau
// ---------------------------------------------------------------------------

if (etat.jeton) {
  ouvrirTableau().catch(() => deconnecter());
} else {
  deconnecter();
}
