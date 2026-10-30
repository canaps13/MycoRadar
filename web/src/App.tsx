import { useEffect, useState } from "react";
import Explorer from "./map/Explorer";

type ApiStatus = "checking" | "online" | "offline";

const statusLabels: Record<ApiStatus, string> = {
  checking: "Vérification du service…",
  online: "Service API disponible",
  offline: "Service API indisponible",
};

export default function App() {
  const [apiStatus, setApiStatus] = useState<ApiStatus>("checking");

  useEffect(() => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    let active = true;

    async function checkHealth() {
      try {
        const response = await fetch("/api/health", {
          signal: controller.signal,
        });
        if (!response.ok) throw new Error("Health request failed");
        const data: unknown = await response.json();
        if (
          typeof data !== "object" ||
          data === null ||
          !("status" in data) ||
          data.status !== "ok" ||
          !("service" in data) ||
          data.service !== "mycoradar-api"
        ) {
          throw new Error("Unexpected health response");
        }
        if (active) setApiStatus("online");
      } catch {
        if (active) setApiStatus("offline");
      } finally {
        clearTimeout(timeout);
      }
    }

    void checkHealth();
    return () => {
      active = false;
      clearTimeout(timeout);
      controller.abort();
    };
  }, []);

  return (
    <>
      <header className="site-header">
        <a className="brand" href="/" aria-label="MycoRadar, accueil">
          <span className="brand-mark" aria-hidden="true">
            M
          </span>
          MycoRadar
        </a>
        <span className="stage">Projet en construction</span>
      </header>
      <main>
        <section className="intro" aria-labelledby="page-title">
          <p className="eyebrow">Écologie · Territoires · Saisons</p>
          <h1 id="page-title">Explorer les territoires.</h1>
          <p className="lead">
            Comprendre les conditions favorables aux champignons, à partir de
            données scientifiques traçables. Un premier pilote en Provence, une
            plateforme pensée pour la France et au-delà.
          </p>
          <div className="availability">
            <span className="dot" aria-hidden="true" />
            <div>
              <strong>Prévisions indisponibles</strong>
              <p>
                Les territoires sont visibles ; les données écologiques restent
                à intégrer.
              </p>
            </div>
          </div>
        </section>
        <Explorer />
        <section
          className="principles"
          aria-label="Trois informations distinctes"
        >
          <article>
            <span className="number">01</span>
            <h2>Habitat</h2>
            <p>
              L’aptitude écologique d’un territoire pour une espèce, selon les
              sols, la végétation et le relief.
            </p>
          </article>
          <article>
            <span className="number">02</span>
            <h2>Fructification</h2>
            <p>
              Les conditions à une date donnée, selon la pluie, la température
              et la disponibilité en eau.
            </p>
          </article>
          <article>
            <span className="number">03</span>
            <h2>Confiance</h2>
            <p>
              La provenance, l’âge, la résolution effective et les limites des
              données utilisées.
            </p>
          </article>
        </section>
        <aside className="science-note">
          Un score de favorabilité sur 100 n’est pas une probabilité de
          présence. Il ne confirme ni l’identification ni la comestibilité d’un
          champignon.
        </aside>
      </main>
      <footer>
        <span>MycoRadar · Des données avant des prédictions.</span>
        <span role="status" className={`api-status ${apiStatus}`}>
          {statusLabels[apiStatus]}
        </span>
      </footer>
    </>
  );
}
