import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MapView from "./MapView";
import catalog from "./catalog.json";

// Model the camera boundary, without WebGL or timing-dependent worker messages.
const engine = vi.hoisted(() => {
  class CameraMap {
    styleLoaded = false;
    camera: { extent: unknown; animating: boolean };
    canvas = document.createElement("canvas");
    constructor(options: { bounds: unknown }) {
      this.camera = { extent: options.bounds, animating: false };
      instances.push(this);
    }
    isStyleLoaded = vi.fn(() => this.styleLoaded);
    stop = vi.fn(() => {
      this.camera.animating = false;
      return this;
    });
    fitBounds = vi.fn((extent: unknown) => {
      this.camera.extent = extent;
      this.camera.animating = false;
      return this;
    });
    getCanvas = () => this.canvas;
    addControl = vi.fn();
    on = vi.fn();
    setFilter = vi.fn();
    resize = vi.fn();
    remove = vi.fn();
  }
  const instances: CameraMap[] = [];
  return { CameraMap, instances };
});

vi.mock("maplibre-gl", () => ({
  Map: engine.CameraMap,
  Marker: class {},
  NavigationControl: class {},
  setWorkerUrl: vi.fn(),
}));

describe("recenter during a camera animation", () => {
  beforeEach(() => {
    engine.instances.length = 0;
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        disconnect() {}
      },
    );
  });

  it.each([false, true])(
    "cancels animation and restores the configured extent with styleLoaded=%s",
    async (styleLoaded) => {
      const onSelect = vi.fn();
      const view = render(
        <MapView selected={null} onSelect={onSelect} reset={0} />,
      );
      await waitFor(() => expect(engine.instances).toHaveLength(1));
      const map = engine.instances[0];
      map.styleLoaded = styleLoaded;
      map.camera = { extent: "zoom in progress", animating: true };

      view.rerender(<MapView selected={null} onSelect={onSelect} reset={1} />);

      expect(map.camera).toEqual({
        extent: [
          [catalog.bounds[0], catalog.bounds[1]],
          [catalog.bounds[2], catalog.bounds[3]],
        ],
        animating: false,
      });
      // Recenter must reuse the renderer and must not manufacture a selection.
      expect(engine.instances).toHaveLength(1);
      expect(map.remove).not.toHaveBeenCalled();
      expect(onSelect).not.toHaveBeenCalled();
    },
  );
});
