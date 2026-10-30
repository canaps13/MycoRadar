import { useCallback, useState } from "react";
import MapView from "./MapView";
import catalog from "./catalog.json";
import { useExploration } from "./exploration";

export default function Explorer() {
  const [selected, setSelected] = useState<string | null>(null);
  const [day, setDay] = useState("");
  const [taxon, setTaxon] = useState("");
  const [reset, setReset] = useState(0);
  const { view, mapData, status, initializing, reload } = useExploration(
    selected,
    day,
    taxon,
  );
  const chooseRegion = useCallback((id: string | null) => {
    setSelected(id);
    setTaxon("");
  }, []);
  const sectors = mapData?.regions ?? catalog.sectors;
  const sector = sectors.find((s) => s.id === selected);
  const sources = [
    ...(mapData?.sources ?? [catalog.sources[0]]),
    catalog.sources[1],
  ];
  const apiSector = mapData?.regions.find((item) => item.id === selected);
  const source = mapData?.sources.find(
    (s) => !apiSector || apiSector.source_ids.includes(s.id),
  );
  const currentDay =
    day || view?.requested_date || new Date().toISOString().slice(0, 10);
  return (
    <section
      className="explorer"
      aria-labelledby="explorer-title"
      data-api-state={status}
    >
      <div className="explorer-heading">
        <div>
          <p className="eyebrow">Un premier territoire d’exploration</p>
          <h2 id="explorer-title">
            Zone pilote · {mapData?.label ?? catalog.label}
          </h2>
        </div>
        <button
          type="button"
          className="reset-map"
          onClick={() => setReset((n) => n + 1)}
        >
          Vue d’ensemble <span aria-hidden="true">↗</span>
        </button>
      </div>
      <div className="explorer-filters">
        <label>
          Espèce pilote
          <select
            value={taxon}
            disabled={!view?.species.length || status !== "partial"}
            onChange={(event) => setTaxon(event.target.value)}
          >
            <option value="">
              {view?.species.length
                ? "Choisir une espèce admise"
                : "Aucune espèce admise"}
            </option>
            {view?.species.map((s) => (
              <option key={s.id} value={s.id}>
                {s.scientific_name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Date d’exploration
          <input
            type="date"
            min="1900-01-01"
            max="2100-12-31"
            value={currentDay}
            onChange={(event) => {
              if (event.currentTarget.validity.valid && event.target.value)
                setDay(event.target.value);
            }}
          />
        </label>
        <span className="date-zone">
          {view
            ? `Calendrier : ${view.timezone}`
            : "Référence UTC hors connexion"}
        </span>
      </div>
      <p className={`data-connection ${status}`} aria-live="polite">
        {status === "loading"
          ? "Chargement des données du territoire…"
          : status === "partial"
            ? "Données partielles · contours API disponibles, conditions écologiques indisponibles."
            : mapData
              ? "API cartographique indisponible · dernière publication reçue conservée pour les contours."
              : "API cartographique indisponible · fond local et sources datées accessibles."}
        {status === "unavailable" && (
          <button type="button" onClick={reload}>
            Recharger les données
          </button>
        )}
      </p>
      <div className="explorer-layout">
        <div className="map-column">
          {initializing ? (
            <div className="map-frame" data-map-state="loading">
              <div className="map-message" aria-live="polite">
                <strong>Chargement de la carte…</strong>
                <p>Lecture de la publication cartographique.</p>
              </div>
            </div>
          ) : (
            <MapView
              key={
                mapData
                  ? `${mapData.catalog_version}:${mapData.context_version}`
                  : "local"
              }
              dataset={mapData}
              selected={selected}
              onSelect={chooseRegion}
              reset={reset}
            />
          )}
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
            Contours :{" "}
            {sources.slice(0, -1).map((s) => (
              <span key={s.id}>
                <a href={s.source_url}>{s.provider}</a> ·{" "}
                <a href={s.license_url}>
                  {s.license === "Etalab-2.0"
                    ? "Licence Ouverte 2.0"
                    : s.license}
                </a>{" "}
                ·{" "}
              </span>
            ))}
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
            {sectors.map((item) => (
              <button
                type="button"
                key={item.id}
                aria-pressed={selected === item.id}
                aria-label={`${item.name} ${item.code}`}
                onClick={() => chooseRegion(item.id)}
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
                : `${sectors.length} secteurs pour découvrir la carte pilote.`}
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
              {status === "loading"
                ? "Actualisation de la sélection. Aucun résultat scientifique affiché pendant le chargement."
                : "Aucun calcul scientifique publié pour cette sélection et cette date. Les contours ne signalent aucune présence de champignon."}
            </p>
            {sector && (
              <button
                type="button"
                className="clear-selection"
                onClick={() => chooseRegion(null)}
              >
                Effacer la sélection
              </button>
            )}
          </div>
          <details className="confidence-detail">
            <summary>Provenance et qualité</summary>
            <dl>
              <div>
                <dt>Origine des contours</dt>
                <dd>{mapData ? "Publication API" : "Fond local"}</dd>
              </div>
              <div>
                <dt>Collecte</dt>
                <dd>
                  {(source?.fetched_at ?? catalog.sources[0].fetched_at).slice(
                    0,
                    10,
                  )}
                </dd>
              </div>
              <div>
                <dt>Âge des données</dt>
                <dd>Inconnu</dd>
              </div>
              <div>
                <dt>Résolution effective</dt>
                <dd>
                  {source?.effective_resolution_m
                    ? `${source.effective_resolution_m} m`
                    : "Non établie"}
                </dd>
              </div>
              <div>
                <dt>Calcul des conditions</dt>
                <dd>Aucun calcul publié</dd>
              </div>
            </dl>
            <p>La date de collecte ne date pas l’acquisition des données.</p>
          </details>
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
          {sources.map((item) => (
            <article key={item.id}>
              <h3>{item.provider}</h3>
              <p>{item.product}</p>
              <dl>
                <div>
                  <dt>Collecte de l’extrait</dt>
                  <dd>
                    <time dateTime={item.fetched_at}>
                      {item.fetched_at.slice(0, 10)}
                    </time>
                  </dd>
                </div>
                <div>
                  <dt>Date de publication</dt>
                  <dd>
                    {item.source_published_at?.slice(0, 10) ?? "Non fournie"}
                  </dd>
                </div>
                <div>
                  <dt>Résolution effective</dt>
                  <dd>
                    {item.effective_resolution_m
                      ? `${item.effective_resolution_m} m`
                      : "Non établie"}
                  </dd>
                </div>
              </dl>
              <p>
                {item.id === "natural-earth"
                  ? "Échelle cartographique 1:10 millions ; ce n’est pas une résolution de 10 mètres."
                  : "Contours simplifiés pour l’affichage. La date de collecte ne garantit pas leur fraîcheur."}
              </p>
              <a href={item.source_url}>Source de l’extrait</a> ·{" "}
              <a href={item.license_url}>{item.license}</a>
              <p className="source-version">Version : {item.version}</p>
            </article>
          ))}
        </div>
        <p>
          <a href="/maplibre-LICENSE.txt">
            Licences du moteur cartographique MapLibre GL JS
          </a>
        </p>
        {mapData && (
          <p className="source-version">
            Catalogue API : {mapData.catalog_version}
          </p>
        )}
      </details>
    </section>
  );
}
