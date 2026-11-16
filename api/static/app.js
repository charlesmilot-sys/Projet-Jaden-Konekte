// Jaden Konekté — tableau de bord (JavaScript sans framework)
"use strict";

const API = "/api/v1";
const SEUIL_ARROSAGE = 25;          // affiché sur la colonne ; viendra de la règle de la parcelle
const DELAI_CONFIRMATION_MS = 35000; // un peu plus que les 30 s du serveur

const etat = {
  jeton: sessionStorage.getItem("jeton"),
  parcelle: null,
  flux: null,               // AbortController du flux SSE en cours
  commandeEnAttente: null,  // { id, minuteur }
  periode: "24h",
  graphique: null,
};

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------------------
// Appels à l'API
// ---------------------------------------------------------------------------

async function api(chemin, options = {}) {
  const reponse = await fetch(API + chemin, {
    ...options,
    headers: {
      "Content-Type": "application/json",
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
}

function choisirParcelle(id) {
  etat.parcelle = id;
  for (const b of $("parcelles").children) {
    b.setAttribute("aria-selected", String(Number(b.dataset.id) === id));
  }
  annulerAttente();
  $("vanne-message").textContent = "";
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
  $("eau").style.height = h ? `${Math.min(100, Math.max(0, h.valeur))}%` : "0";
  $("seuil").style.bottom = `${SEUIL_ARROSAGE}%`;
  $("seuil-valeur").textContent = SEUIL_ARROSAGE;
  document.querySelector(".sol").classList.toggle("sec", !!h && h.valeur < SEUIL_ARROSAGE);

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
// Démarrage : si un jeton est déjà en mémoire, on va directement au tableau
// ---------------------------------------------------------------------------

if (etat.jeton) {
  ouvrirTableau().catch(() => deconnecter());
} else {
  deconnecter();
}
