import { useState } from "react";
import MapView from "./MapView";
import catalog from "./catalog.json";

export default function Explorer() {
  const [selected, setSelected] = useState<string | null>(null);
  const [reset, setReset] = useState(0);
  const sector = catalog.sectors.find((s) => s.id === selected);
  return (
    <section className="explorer" aria-labelledby="explorer-title">
      <div className="explorer-heading">
        <div>
          <p className="eyebrow">Un premier territoire d’exploration</p>
          <h2 id="explorer-title">Zone pilote · {catalog.label}</h2>
        </div>
        <button
          type="button"
          className="reset-map"
          onClick={() => setReset((n) => n + 1)}
        >
          Vue d’ensemble <span aria-hidden="true">↗</span>
        </button>
      </div>
      <div className="explorer-layout">
        <div className="map-column">
          <MapView selected={selected} onSelect={setSelected} reset={reset} />
          <ul className="legend" aria-label="Légende de la carte">
            <li>
              <span className="swatch pilot" />
              Territoire pilote
            </li>
            <li>
              <span className="swatch selected" />
              Secteur sélectionné
            </li>
          </ul>
          <p className="map-credits">
            Contours © <a href={catalog.sources[0].source_url}>IGN</a> ·{" "}
            <a href={catalog.sources[0].license_url}>Licence Ouverte 2.0</a> ·
            Fond <a href={catalog.sources[1].license_url}>Natural Earth</a>{" "}
            (domaine public) · <a href="https://maplibre.org/">MapLibre</a>
          </p>
        </div>
        <aside className="sector-panel" aria-label="Sélection du secteur">
          <span className="panel-kicker">Explorer un secteur</span>
          <p className="panel-help">
            Touchez la carte ou choisissez un territoire.
          </p>
          <div className="sector-list" aria-label="Secteurs pilotes">
            {catalog.sectors.map((item) => (
              <button
                type="button"
                key={item.id}
                aria-pressed={selected === item.id}
                aria-label={`${item.name} ${item.code}`}
                onClick={() => setSelected(item.id)}
              >
                <span>{item.name}</span>
                <span className="sector-code">{item.code}</span>
              </button>
            ))}
          </div>
          <div className="selection-detail" aria-live="polite">
            <h3>{sector?.name ?? "À vous d’explorer"}</h3>
            <p>
              {sector
                ? `Secteur administratif ${sector.id}.`
                : `${catalog.sectors.length} secteurs pour découvrir la carte pilote.`}
            </p>
            <dl>
              <div>
                <dt>Habitat</dt>
                <dd>Indisponible</dd>
              </div>
              <div>
                <dt>Fructification</dt>
                <dd>Indisponible</dd>
              </div>
            </dl>
            <p className="data-note">
              Les contours situent le territoire. Aucune donnée écologique ni
              observation de champignon n’y est associée.
            </p>
            {sector && (
              <button
                type="button"
                className="clear-selection"
                onClick={() => setSelected(null)}
              >
                Effacer la sélection
              </button>
            )}
          </div>
        </aside>
      </div>
      <details className="map-sources">
        <summary>Sources, dates et limites cartographiques</summary>
        <p>
          Fond de contexte généralisé, sans routes ni limites de propriété. Les
          couleurs indiquent uniquement les secteurs administratifs, jamais une
          favorabilité. Elles n’indiquent aucun droit d’accès.
        </p>
        <div className="source-grid">
          {catalog.sources.map((source) => (
            <article key={source.id}>
              <h3>{source.provider}</h3>
              <p>{source.product}</p>
              <dl>
                <div>
                  <dt>Collecte de l’extrait</dt>
                  <dd>
                    <time dateTime={source.fetched_at}>
                      {source.fetched_at.slice(0, 10)}
                    </time>
                  </dd>
                </div>
                <div>
                  <dt>Date de publication</dt>
                  <dd>Non fournie</dd>
                </div>
                <div>
                  <dt>Résolution effective</dt>
                  <dd>Non établie</dd>
                </div>
              </dl>
              <p>
                {source.id === "natural-earth"
                  ? "Échelle cartographique 1:10 millions ; ce n’est pas une résolution de 10 mètres."
                  : "Service LATEST : l’extrait ne permet pas de dater l’édition IGN. Contours simplifiés pour l’affichage."}
              </p>
              <a href={source.source_url}>Source de l’extrait</a> ·{" "}
              <a href={source.license_url}>{source.license}</a>
              <p className="source-version">Version : {source.version}</p>
            </article>
          ))}
        </div>
        <p>
          <a href="/maplibre-LICENSE.txt">
            Licences du moteur cartographique MapLibre GL JS
          </a>
        </p>
      </details>
    </section>
  );
}
