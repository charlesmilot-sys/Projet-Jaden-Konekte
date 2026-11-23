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
    const erreur = new Error(corps?.detail || `Erreur ${reponse.status}`);
    erreur.corps = corps;          // détail par champ pour les erreurs 422
    throw erreur;
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

// Inscription : crée toujours un compte exploitant, puis connecte directement
function montrerFormulaire(inscription) {
  $("form-connexion").hidden = inscription;
  $("form-inscription").hidden = !inscription;
  $("erreur-connexion").textContent = "";
  $("erreur-inscription").textContent = "";
  $(inscription ? "ins-prenom" : "courriel").focus();
}
$("vers-inscription").addEventListener("click", () => montrerFormulaire(true));
$("vers-connexion").addEventListener("click", () => montrerFormulaire(false));

$("form-inscription").addEventListener("submit", async (e) => {
  e.preventDefault();
  const erreur = $("erreur-inscription");
  erreur.textContent = "";
  const courriel = $("ins-courriel").value.trim();
  const mot_de_passe = $("ins-mdp").value;
  if (mot_de_passe.length < 8) {
    erreur.textContent = "Le mot de passe doit contenir au moins 8 caractères.";
    return;
  }
  try {
    await api("/utilisateurs", {
      method: "POST",
      body: JSON.stringify({ prenom: $("ins-prenom").value.trim(), nom: $("ins-nom").value.trim(),
                             courriel, mot_de_passe }),
    });
    const jeton = await api("/jetons", { method: "POST", body: JSON.stringify({ courriel, mot_de_passe }) });
    etat.jeton = jeton.access_token;
    sessionStorage.setItem("jeton", etat.jeton);
    $("form-inscription").reset();
    montrerFormulaire(false);
    await ouvrirTableau();
  } catch (err) {
    // 409 : courriel déjà utilisé ; 422 : l'API indique le champ invalide
    const NOMS = { prenom: "Prénom", nom: "Nom", courriel: "Courriel", mot_de_passe: "Mot de passe" };
    const champs = (err.corps?.erreurs || []).map((x) => NOMS[x.champ.split(".").pop()]).filter(Boolean);
    erreur.textContent = champs.length ? `Champ à corriger : ${[...new Set(champs)].join(", ")}.` : err.message;
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
  const [page, moi] = await Promise.all([api("/parcelles?taille=100"), api("/utilisateurs/moi")]);
  etat.moi = moi;
  $("ecran-connexion").hidden = true;
  $("ecran-tableau").hidden = false;
  $("admin").hidden = moi.role !== "administrateur";
  $("lien-admin").hidden = moi.role !== "administrateur";
  if (moi.role === "administrateur") chargerAdmin();

  afficherOnglets(page.elements);
  if (page.elements.length > 0) choisirParcelle(page.elements[0].id);
  chargerApercu();
  chargerDiagnostics();
}

function afficherOnglets(parcelles) {
  const nav = $("parcelles");
  nav.replaceChildren();
  if (parcelles.length === 0) {
    nav.textContent = "Aucune parcelle n'est rattachée à votre compte.";
    return;
  }
  for (const p of parcelles) {
    const bouton = document.createElement("button");
    bouton.textContent = `${p.nom} (${p.culture})`;
    bouton.setAttribute("role", "tab");
    bouton.dataset.id = p.id;
    bouton.setAttribute("aria-selected", String(p.id === etat.parcelle));
    bouton.addEventListener("click", () => choisirParcelle(p.id));
    nav.append(bouton);
  }
}

// Après une création ou une attribution : on garde la parcelle affichée si elle existe toujours
async function rafraichirParcelles() {
  const page = await api("/parcelles?taille=100");
  afficherOnglets(page.elements);
  if (!page.elements.some((p) => p.id === etat.parcelle) && page.elements.length > 0) {
    choisirParcelle(page.elements[0].id);
  }
  chargerApercu();
  return page.elements;
}

function choisirParcelle(id) {
  etat.parcelle = id;
  for (const b of $("parcelles").children) {
    b.setAttribute("aria-selected", String(Number(b.dataset.id) === id));
  }
  for (const c of document.querySelectorAll(".carte")) {
    c.setAttribute("aria-current", String(Number(c.dataset.id) === id));
  }
  annulerAttente();
  $("vanne-message").textContent = "";
  ecouterFlux(id);
  // Le graphique d'humidité trace le seuil de la règle : on lit la règle d'abord
  chargerRegle(id).then(chargerHistorique);
  chargerJournal(id);
}

// ---------------------------------------------------------------------------
// Vue d'ensemble : toutes les parcelles d'un coup d'œil
// ---------------------------------------------------------------------------

async function chargerApercu() {
  let parcelles;
  try {
    parcelles = await api("/apercu");
  } catch {
    return;   // la vue détaillée reste utilisable
  }
  afficherApercu(parcelles);
}

// L'état d'une parcelle, du plus urgent au plus calme
function etatParcelle(p) {
  if (!p.en_ligne) return { genre: "alerte", texte: "Capteurs hors ligne" };
  if (p.humidite_fiable === false) return { genre: "alerte", texte: "Capteur d'humidité en panne" };
  if (p.vanne_etat === "ouverte") {
    const fin = p.vanne_jusqua
      ? ` jusqu'à ${new Intl.DateTimeFormat("fr-FR", { timeStyle: "short" }).format(new Date(p.vanne_jusqua))}`
      : "";
    return { genre: "arrosage", texte: `Arrosage en cours${fin}` };
  }
  if (p.humidite === null) return { genre: "neutre", texte: "Pas encore de mesure" };
  if (p.seuil !== null && p.humidite < p.seuil) {
    return { genre: "sec", texte: p.regle_active ? "Sol sec : arrosage automatique attendu" : "Sol sec, sous le seuil" };
  }
  return { genre: "ok", texte: "Humidité correcte" };
}

function afficherApercu(parcelles) {
  const liste = $("apercu-liste");
  liste.replaceChildren();
  const compte = { arrosage: 0, sec: 0, alerte: 0 };

  for (const p of parcelles) {
    const e = etatParcelle(p);
    if (e.genre in compte) compte[e.genre] += 1;

    const carte = document.createElement("button");
    carte.type = "button";
    carte.className = `carte ${p.humidite_fiable === false ? "panne" : ""}`;
    carte.dataset.id = p.id;
    carte.setAttribute("aria-current", String(p.id === etat.parcelle));
    carte.addEventListener("click", () => {
      choisirParcelle(p.id);
      document.querySelector(".sol").scrollIntoView({ behavior: "smooth", block: "start" });
    });

    // Petite colonne de sol, comme la grande : l'eau monte jusqu'à l'humidité, le trait marque le seuil
    const colonne = document.createElement("span");
    colonne.className = "mini-colonne";
    colonne.setAttribute("aria-hidden", "true");
    const eau = document.createElement("span");
    eau.className = "eau";
    eau.style.height = p.humidite === null ? "0" : `${Math.min(100, Math.max(0, p.humidite))}%`;
    colonne.append(eau);
    if (p.seuil !== null) {
      const trait = document.createElement("span");
      trait.className = "seuil";
      trait.style.bottom = `${p.seuil}%`;
      colonne.append(trait);
    }

    const texte = document.createElement("span");
    texte.className = "carte-texte";
    const ligne = (classe, contenu) => Object.assign(document.createElement("span"), { className: classe, textContent: contenu });
    const chiffre = ligne("carte-chiffre", p.humidite === null ? "–" : nombre(p.humidite, 0));
    chiffre.append(Object.assign(document.createElement("small"), {
      textContent: p.seuil !== null ? ` % (seuil ${nombre(p.seuil, 0)} %)` : " %",
    }));
    const arrosages = p.arrosages_24h === 0 ? "Aucun arrosage en 24 h"
      : `${p.arrosages_24h} arrosage${p.arrosages_24h > 1 ? "s" : ""} en 24 h`;
    texte.append(
      ligne("carte-nom", p.nom),
      ligne("carte-culture", p.culture),
      chiffre,
      ligne(`carte-etat ${e.genre}`, e.texte),
      ligne("carte-arrosages", arrosages),
    );

    carte.append(colonne, texte);
    const li = document.createElement("li");
    li.append(carte);
    liste.append(li);
  }

  // Une phrase qui résume, pour savoir tout de suite s'il faut agir
  const n = parcelles.length;
  const details = [];
  if (compte.arrosage) details.push(`${compte.arrosage} en cours d'arrosage`);
  if (compte.sec) details.push(`${compte.sec} sous le seuil d'arrosage`);
  if (compte.alerte) details.push(`${compte.alerte} à vérifier (capteur en panne ou hors ligne)`);
  $("apercu-resume").textContent = n === 0 ? ""
    : details.length ? `${n} parcelle${n > 1 ? "s" : ""} : ${details.join(", ")}.`
    : `${n} parcelle${n > 1 ? "s" : ""}, humidité correcte partout.`;
}

setInterval(() => { if (etat.jeton && etat.parcelle) chargerApercu(); }, 10000);

// ---------------------------------------------------------------------------
// Journal d'arrosage de la parcelle choisie
// ---------------------------------------------------------------------------

const ORIGINES = { manuelle: "Manuelle", regle: "Règle automatique", agent: "Assistant" };
const RESULTATS = { confirmee: "Confirmé par la vanne", echec: "Pas de réponse de la vanne", envoyee: "En attente" };

async function chargerJournal(id = etat.parcelle) {
  let commandes;
  try {
    commandes = await api(`/parcelles/${id}/commandes?limite=20`);
  } catch {
    return;
  }
  if (id !== etat.parcelle) return;   // l'utilisateur a changé de parcelle entre-temps

  const corps = $("journal-lignes");
  corps.replaceChildren();
  for (const c of commandes) {
    const tr = document.createElement("tr");
    const cellule = (contenu, classe = "") => Object.assign(document.createElement("td"), { textContent: contenu, className: classe });
    const ordre = c.action === "ouvrir"
      ? `Ouverture${c.duree_s ? ` ${Math.round(c.duree_s / 60)} min` : ""}`
      : "Fermeture";
    tr.append(
      cellule(format.format(new Date(c.cree_le))),
      cellule(ordre),
      cellule(ORIGINES[c.origine] ?? c.origine, `origine-${c.origine}`),
      cellule(RESULTATS[c.statut] ?? c.statut, `resultat-${c.statut}`),
    );
    corps.append(tr);
  }
  $("journal-vide").hidden = commandes.length > 0;
  document.querySelector(".journal table").hidden = commandes.length === 0;
}

setInterval(() => { if (etat.jeton && etat.parcelle) chargerJournal(); }, 10000);

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
    chargerJournal();
    chargerApercu();
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
    chargerJournal();
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
    chargerApercu();
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

const NOMS_GRANDEURS = { humidite: "Humidité du sol", temperature: "Température", luminosite: "Luminosité", intensite: "Pluie" };
const COULEUR = { eau: "#1f6fa8", terre: "#8b5e3c", alerte: "#b03a26", trait: "#e3e9e0", discret: "#5b6a5f", encre: "#1e2b22" };

const POLICE = "'Atkinson Hyperlegible', system-ui, sans-serif";

// Petit greffon Chart.js : écrit « Seuil 40 % » au bout de la ligne de seuil
const etiquetteSeuil = {
  id: "etiquetteSeuil",
  afterDatasetsDraw(chart) {
    const seuil = chart.options.plugins.etiquetteSeuil?.valeur;
    if (seuil == null) return;
    const { ctx, chartArea, scales } = chart;
    const y = scales.y.getPixelForValue(seuil);
    if (y < chartArea.top || y > chartArea.bottom) return;
    const texte = `Seuil ${nombre(seuil)} %`;
    ctx.save();
    ctx.font = `700 12px ${POLICE}`;
    const largeur = ctx.measureText(texte).width + 12;
    const x = chartArea.right - largeur;
    ctx.fillStyle = "#fff";
    ctx.fillRect(x, y - 10, largeur, 20);
    ctx.fillStyle = COULEUR.alerte;
    ctx.textBaseline = "middle";
    ctx.fillText(texte, x + 6, y);
    ctx.restore();
  },
};

async function chargerHistorique() {
  const grandeur = $("grandeur").value;
  let serie;
  try {
    serie = await api(`/parcelles/${etat.parcelle}/mesures?grandeur=${grandeur}&periode=${etat.periode}`);
  } catch (err) {
    $("historique-message").textContent = err.message;
    return;
  }
  const points = serie.points;
  const vide = points.length === 0;
  $("zone-graphique").hidden = vide;
  $("historique-stats").hidden = vide;
  const avecSeuil = grandeur === "humidite" && etat.regle !== null;
  const decimales = grandeur === "luminosite" ? 0 : 1;
  const unite = serie.unite;

  // Chiffres clés de la période
  if (!vide) {
    const moyennes = points.map((p) => p.moyenne);
    const moyenne = moyennes.reduce((a, b) => a + b, 0) / moyennes.length;
    const heuresTranche = serie.intervalle === "1 hour" ? 1 : 6;
    const stats = [
      ["Moyenne", `${nombre(moyenne, decimales)} ${unite}`],
      ["Minimum", `${nombre(Math.min(...points.map((p) => p.min)), decimales)} ${unite}`],
      ["Maximum", `${nombre(Math.max(...points.map((p) => p.max)), decimales)} ${unite}`],
    ];
    if (avecSeuil) {
      const sous = points.filter((p) => p.moyenne < etat.seuil).length * heuresTranche;
      stats.push(["Temps sous le seuil", `${sous} h sur ${points.length * heuresTranche} h`]);
    }
    const zone = $("historique-stats");
    zone.replaceChildren(...stats.map(([nom, valeur]) => {
      const div = document.createElement("div");
      div.append(Object.assign(document.createElement("dt"), { textContent: nom }),
                 Object.assign(document.createElement("dd"), { textContent: valeur }));
      return div;
    }));
  }
  $("historique-message").textContent = vide
    ? "Pas encore de mesures valides sur cette période."
    : `Moyenne par tranche de ${serie.intervalle === "1 hour" ? "1 heure" : "6 heures"}, avec la plage minimum–maximum en zone claire.`
      + (avecSeuil ? " La courbe passe en brun quand le sol est sous le seuil d'arrosage." : "");
  if (vide) return;

  if (!window.Chart) {
    $("historique-message").textContent = "La bibliothèque de graphiques n'a pas pu être chargée.";
    return;
  }

  const dates = points.map((p) => new Date(p.debut));
  const etiquette = (d) => d.toLocaleString("fr-FR", etat.periode === "24h"
    ? { hour: "2-digit", minute: "2-digit" }
    : { weekday: "short", day: "numeric", hour: "2-digit" });
  const sousSeuil = (ctx) => avecSeuil && (ctx.p0.parsed.y < etat.seuil || ctx.p1.parsed.y < etat.seuil);

  const donnees = {
    labels: dates.map(etiquette),
    datasets: [
      { label: "Maximum", data: points.map((p) => p.max), borderWidth: 0, pointRadius: 0, pointHitRadius: 0, pointHoverRadius: 0,
        backgroundColor: "rgba(31, 111, 168, .12)", fill: "+1", tension: .35 },
      { label: "Minimum", data: points.map((p) => p.min), borderWidth: 0, pointRadius: 0, pointHitRadius: 0, pointHoverRadius: 0,
        fill: false, tension: .35 },
      { label: "Moyenne", data: points.map((p) => p.moyenne), borderColor: COULEUR.eau, borderWidth: 2.5,
        pointRadius: 0, pointHoverRadius: 5, pointHoverBackgroundColor: COULEUR.eau, pointHoverBorderColor: "#fff",
        pointHoverBorderWidth: 2, tension: .35, fill: false,
        segment: { borderColor: (ctx) => (sousSeuil(ctx) ? COULEUR.terre : undefined) } },
    ],
  };
  if (avecSeuil) {
    donnees.datasets.push({ label: "Seuil", data: points.map(() => etat.seuil), borderColor: COULEUR.alerte,
      borderDash: [6, 5], borderWidth: 1.5, pointRadius: 0, pointHitRadius: 0, pointHoverRadius: 0, fill: false });
  }

  const options = {
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: "index", intersect: false },
    layout: { padding: { top: 8, right: 4 } },
    plugins: {
      legend: { display: false },
      etiquetteSeuil: { valeur: avecSeuil ? etat.seuil : null },
      tooltip: {
        backgroundColor: COULEUR.encre, padding: 10, cornerRadius: 6, displayColors: false,
        titleFont: { family: POLICE, weight: "700" }, bodyFont: { family: POLICE },
        filter: (item) => item.dataset.label === "Moyenne",
        callbacks: {
          title: (items) => dates[items[0].dataIndex].toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" }),
          label: (item) => {
            const p = points[item.dataIndex];
            const lignes = [
              `${NOMS_GRANDEURS[grandeur]} moyenne : ${nombre(p.moyenne, decimales)} ${unite}`,
              `Plage : ${nombre(p.min, decimales)} à ${nombre(p.max, decimales)} ${unite}`,
              `${p.nombre} mesures`,
            ];
            if (avecSeuil) lignes.push(p.moyenne < etat.seuil ? "Sous le seuil d'arrosage" : "Au-dessus du seuil");
            return lignes;
          },
        },
      },
    },
    scales: {
      x: {
        grid: { display: false }, border: { color: COULEUR.trait },
        ticks: { color: COULEUR.discret, maxRotation: 0, autoSkipPadding: 18, font: { family: POLICE } },
      },
      y: {
        grid: { color: COULEUR.trait }, border: { display: false },
        title: { display: true, text: `${NOMS_GRANDEURS[grandeur]} (${unite})`, color: COULEUR.discret,
                 font: { family: POLICE, size: 12 } },
        ticks: { color: COULEUR.discret, padding: 8, font: { family: POLICE },
                 callback: (v) => nombre(v, decimales) },
        // Humidité : une marge de 10 points autour des valeurs et du seuil, sans sortir de 0–100 %
        ...(grandeur === "humidite" ? {
          min: Math.max(0, Math.floor((Math.min(...points.map((p) => p.min), avecSeuil ? etat.seuil : 100) - 10) / 10) * 10),
          max: Math.min(100, Math.ceil((Math.max(...points.map((p) => p.max), avecSeuil ? etat.seuil : 0) + 10) / 10) * 10),
        } : {}),
        ...(grandeur === "intensite" || grandeur === "luminosite" ? { beginAtZero: true } : {}),
      },
    },
  };

  // Une nouvelle courbe à chaque changement : les options (seuil, axe, unité) changent avec la grandeur
  etat.graphique?.destroy();
  etat.graphique = new Chart($("graphique"), { type: "line", data: donnees, options, plugins: [etiquetteSeuil] });
}

// ---------------------------------------------------------------------------
// Administration : créer une parcelle et l'attribuer à un exploitant
// ---------------------------------------------------------------------------

async function chargerAdmin() {
  let comptes, parcelles;
  try {
    [comptes, { elements: parcelles }] = await Promise.all([api("/utilisateurs"), api("/parcelles?taille=100")]);
  } catch (err) {
    messageAdmin(err.message, "ko");
    return;
  }
  etat.exploitants = comptes.filter((c) => c.role === "exploitant");
  const option = (c) => Object.assign(document.createElement("option"), {
    value: c.id, textContent: `${c.prenom} ${c.nom} (${c.courriel})`,
  });

  const choix = $("np-proprietaire");
  const garde = choix.value;
  choix.replaceChildren(
    Object.assign(document.createElement("option"), { value: "", textContent: "Choisir un exploitant…" }),
    ...etat.exploitants.map(option),
  );
  choix.value = garde;

  const corps = $("admin-lignes");
  corps.replaceChildren();
  for (const p of parcelles) {
    const tr = document.createElement("tr");
    const cellule = (contenu) => Object.assign(document.createElement("td"), { textContent: contenu });
    const select = document.createElement("select");
    select.setAttribute("aria-label", `Exploitant de la parcelle ${p.nom}`);
    select.append(...etat.exploitants.map(option));
    select.value = String(p.proprietaire);
    const bouton = Object.assign(document.createElement("button"), {
      type: "button", className: "bouton-secondaire", textContent: "Attribuer", disabled: true,
    });
    select.addEventListener("change", () => { bouton.disabled = select.value === String(p.proprietaire); });
    bouton.addEventListener("click", () => attribuer(p, Number(select.value)));
    const action = document.createElement("td");
    action.className = "attribution";
    action.append(select, bouton);
    tr.append(cellule(p.nom), cellule(p.culture), cellule(p.proprietaire_nom ?? "–"), action);
    corps.append(tr);
  }
}

function messageAdmin(texte, genre) {
  $("admin-message").textContent = texte;
  $("admin-message").className = `message ${genre}`;
}

// L'API demande la commune quand l'exploitant n'a pas encore d'exploitation
const communeManquante = (err) => /commune/i.test(err.message);

$("form-parcelle").addEventListener("submit", async (e) => {
  e.preventDefault();
  const surface = $("np-surface").value;
  const corps = {
    proprietaire: Number($("np-proprietaire").value),
    nom: $("np-nom").value.trim(),
    culture: $("np-culture").value.trim(),
    seuil: Number($("np-seuil").value),
    ...(surface ? { surface_m2: Number(surface) } : {}),
    ...($("np-commune").value.trim() ? { commune: $("np-commune").value.trim() } : {}),
  };
  if (!corps.proprietaire) return messageAdmin("Choisissez l'exploitant à qui attribuer la parcelle.", "ko");
  try {
    const p = await api("/parcelles", { method: "POST", body: JSON.stringify(corps) });
    $("form-parcelle").reset();
    messageAdmin(`Parcelle « ${p.nom} » créée pour ${p.proprietaire_nom}. Les premières mesures arrivent dans quelques secondes.`, "ok");
    await rafraichirParcelles();
    chargerAdmin();
  } catch (err) {
    if (communeManquante(err)) {
      $("np-commune").focus();
      return messageAdmin("Cet exploitant n'a pas encore d'exploitation : indiquez sa commune, puis créez la parcelle.", "ko");
    }
    const champs = (err.corps?.erreurs || []).map((x) => x.champ.split(".").pop());
    messageAdmin(champs.length ? `Champ à corriger : ${[...new Set(champs)].join(", ")}.` : err.message, "ko");
  }
});

async function attribuer(parcelle, proprietaire, commune) {
  try {
    const p = await api(`/parcelles/${parcelle.id}`, {
      method: "PATCH",
      body: JSON.stringify({ proprietaire, ...(commune ? { commune } : {}) }),
    });
    messageAdmin(`« ${p.nom} » est maintenant attribuée à ${p.proprietaire_nom}.`, "ok");
    await rafraichirParcelles();
    chargerAdmin();
  } catch (err) {
    if (communeManquante(err) && !commune) {
      const exploitant = etat.exploitants.find((c) => c.id === proprietaire);
      const reponse = window.prompt(`${exploitant?.prenom ?? "Cet exploitant"} n'a pas encore d'exploitation. Dans quelle commune ?`);
      if (reponse?.trim()) return attribuer(parcelle, proprietaire, reponse.trim());
      return messageAdmin("Attribution annulée : la commune est nécessaire.", "ko");
    }
    messageAdmin(err.message, "ko");
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
      const erreur = new Error(corps?.detail || `Erreur ${reponse.status}`);
    erreur.corps = corps;          // détail par champ pour les erreurs 422
    throw erreur;
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
