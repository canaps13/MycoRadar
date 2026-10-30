import { useEffect, useRef, useState } from "react";
import type {
  LngLatBoundsLike,
  Map as MapLibreMap,
  StyleSpecification,
} from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import "maplibre-gl/dist/maplibre-gl.css";
import catalog from "./catalog.json";

export function bounds(values: number[]): LngLatBoundsLike {
  return [
    [values[0], values[1]],
    [values[2], values[3]],
  ];
}

export function mapStyle(): StyleSpecification {
  return {
    version: 8,
    sources: {
      land: { type: "geojson", data: catalog.land_url },
      sectors: { type: "geojson", data: catalog.sectors_url },
    },
    layers: [
      {
        id: "water",
        type: "background",
        paint: { "background-color": "#dae7e6" },
      },
      {
        id: "land",
        type: "fill",
        source: "land",
        paint: { "fill-color": "#e7eadc" },
      },
      {
        id: "coast",
        type: "line",
        source: "land",
        paint: { "line-color": "#a9c0b6", "line-width": 1 },
      },
      {
        id: "sectors",
        type: "fill",
        source: "sectors",
        paint: { "fill-color": "#617f57", "fill-opacity": 0.2 },
      },
      {
        id: "selected",
        type: "fill",
        source: "sectors",
        filter: ["==", "id", ""],
        paint: { "fill-color": "#dca04b", "fill-opacity": 0.55 },
      },
      {
        id: "boundaries",
        type: "line",
        source: "sectors",
        paint: { "line-color": "#45684f", "line-width": 1.5 },
      },
    ],
  };
}

type Props = {
  selected: string | null;
  onSelect: (id: string | null) => void;
  reset: number;
};

export default function MapView({ selected, onSelect, reset }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const instance = useRef<MapLibreMap | null>(null);
  const selection = useRef(selected);
  const [state, setState] = useState<"loading" | "ready" | "unavailable">(
    "loading",
  );
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    selection.current = selected;
    const map = instance.current;
    if (map?.isStyleLoaded())
      map.setFilter("selected", ["==", "id", selected ?? ""]);
  }, [selected]);

  useEffect(() => {
    const map = instance.current;
    if (map?.isStyleLoaded())
      map.fitBounds(bounds(catalog.bounds), { padding: 44, duration: 0 });
  }, [reset]);

  useEffect(() => {
    let active = true;
    let observer: ResizeObserver | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let map: MapLibreMap | undefined;
    let failed = false;
    const fail = () => {
      failed = true;
      if (active) setState("unavailable");
    };
    async function initialize() {
      try {
        const { Map, Marker, NavigationControl, setWorkerUrl } =
          await import("maplibre-gl");
        if (!active || !container.current) return;
        setWorkerUrl(workerUrl);
        map = new Map({
          container: container.current,
          style: mapStyle(),
          bounds: bounds(catalog.bounds),
          fitBoundsOptions: { padding: 44 },
          maxBounds: bounds(catalog.context_bounds),
          minZoom: 4,
          maxZoom: 11,
          attributionControl: false,
          dragRotate: false,
          pitchWithRotate: false,
          touchPitch: false,
          cooperativeGestures: true,
          locale: {
            "NavigationControl.ZoomIn": "Zoom avant",
            "NavigationControl.ZoomOut": "Zoom arrière",
            "CooperativeGesturesHandler.WindowsHelpText":
              "Utilisez Ctrl + la molette pour zoomer",
            "CooperativeGesturesHandler.MacHelpText":
              "Utilisez ⌘ + la molette pour zoomer",
            "CooperativeGesturesHandler.MobileHelpText":
              "Utilisez deux doigts pour déplacer la carte",
          },
        });
        instance.current = map;
        map
          .getCanvas()
          .setAttribute(
            "aria-label",
            "Carte des secteurs pilotes ; sélection également disponible dans la liste",
          );
        map.addControl(
          new NavigationControl({ showCompass: false }),
          "top-right",
        );
        map.on("error", fail);
        map.getCanvas().addEventListener("webglcontextlost", fail);
        timer = setTimeout(fail, 15000);
        map.on("load", () => {
          if (!active || !map || failed) return;
          clearTimeout(timer);
          map.setFilter("selected", ["==", "id", selection.current ?? ""]);
          for (const sector of catalog.sectors) {
            const label = document.createElement("span");
            label.className = "sector-label";
            label.dataset.sector = sector.id;
            label.textContent = sector.name;
            label.setAttribute("aria-hidden", "true");
            new Marker({ element: label })
              .setLngLat([sector.label_point[0], sector.label_point[1]])
              .addTo(map);
          }
          setState("ready");
        });
        map.on("click", "sectors", (event) => {
          const id: unknown = event.features?.[0]?.properties.id;
          if (
            typeof id === "string" &&
            catalog.sectors.some((s) => s.id === id)
          )
            onSelect(id);
        });
        map.on("mouseenter", "sectors", () => {
          if (map) map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", "sectors", () => {
          if (map) map.getCanvas().style.cursor = "";
        });
        observer = new ResizeObserver(() => map?.resize());
        observer.observe(container.current);
      } catch {
        fail();
      }
    }
    void initialize();
    return () => {
      active = false;
      clearTimeout(timer);
      observer?.disconnect();
      map?.remove();
      instance.current = null;
    };
  }, [attempt, onSelect]);

  return (
    <div className="map-frame" data-map-state={state}>
      <div ref={container} className="map-canvas" />
      {state !== "ready" && (
        <div className="map-message" aria-live="polite">
          <strong>
            {state === "loading"
              ? "Chargement de la carte…"
              : "Carte indisponible"}
          </strong>
          <p>
            {state === "loading"
              ? "Préparation du fond et des secteurs pilotes."
              : "Les secteurs restent accessibles dans la liste ci-dessous."}
          </p>
          {state === "unavailable" && (
            <button
              type="button"
              onClick={() => {
                setState("loading");
                setAttempt((n) => n + 1);
              }}
            >
              Réessayer la carte
            </button>
          )}
        </div>
      )}
      <span className="map-caption">
        Contours administratifs · aucune donnée de présence
      </span>
    </div>
  );
}
