import React, { useEffect, useRef, useState } from 'react';
import * as PIXI from 'pixi.js';
import { Live2DModel } from 'pixi-live2d-display';
import { globalStateManager } from "@/lib/globalStateManager";

declare global {
  interface Window {
    PIXI: typeof PIXI;
  }
}

interface Live2DCanvasProps {
  modelPath: string;
  /** Model centre as a percentage of the stage width (0 = left edge, 100 = right edge). */
  xPosition: number;
  /** Model centre as a percentage of the stage height (0 = top, 100 = bottom). */
  yPosition: number;
  /** Scale factor relative to the model's native size. */
  scale: number;
  onStatus?: (status: "loading" | "ready" | "error", message?: string) => void;
}

const Live2DCanvas: React.FC<Live2DCanvasProps> = ({ modelPath, xPosition, yPosition, scale, onStatus }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const appRef = useRef<PIXI.Application | null>(null);
  const modelRef = useRef<Live2DModel | null>(null);
  const transform = useRef({ xPosition, yPosition, scale });
  const [error, setError] = useState<string | null>(null);
  transform.current = { xPosition, yPosition, scale };

  // Positions are relative to the stage (this component's box), not the browser window.
  const applyTransform = () => {
    const app = appRef.current;
    const model = modelRef.current;
    if (!app || !model) return;
    const { xPosition, yPosition, scale } = transform.current;
    model.x = (xPosition / 100) * app.screen.width;
    model.y = (yPosition / 100) * app.screen.height;
    model.scale.set(scale, scale);
  };

  useEffect(() => {
    window.PIXI = PIXI;
    const container = containerRef.current;
    if (!container) return;

    const app = new PIXI.Application({ resizeTo: container, backgroundAlpha: 0, antialias: true });
    container.appendChild(app.view as HTMLCanvasElement);
    appRef.current = app;
    let cancelled = false;
    setError(null);
    onStatus?.("loading");

    const model = Live2DModel.fromSync(modelPath, {
      autoInteract: false,
      onError: (e: Error) => {
        if (cancelled) return;
        console.warn(e);
        setError("This Live2D model could not be loaded. Make sure the folder contains its .model3.json and all textures.");
        onStatus?.("error", String(e));
      },
    });
    model.once('load', () => {
      if (cancelled) { model.destroy(); return; }
      model.anchor.set(0.5, 0.5);
      app.stage.addChild(model);
      modelRef.current = model;
      applyTransform();
      onStatus?.("ready");
      app.ticker.add(() => {
        const volume = globalStateManager.getState("ttsLiveVolume");
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (model.internalModel.coreModel as any).setParameterValueById("ParamMouthOpen", volume);
      });
    });

    // Follow the container size (sidebar, inspector panel, window) and re-place the model.
    const observer = new ResizeObserver(() => {
      app.resize();
      applyTransform();
    });
    observer.observe(container);

    return () => {
      cancelled = true;
      observer.disconnect();
      modelRef.current = null;
      appRef.current = null;
      app.destroy(true, { children: true, texture: true, baseTexture: true });
    };
  }, [modelPath]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(applyTransform, [xPosition, yPosition, scale]);

  return (
    <div ref={containerRef} className="relative h-full w-full overflow-hidden">
      {error && (
        <div className="absolute inset-0 grid place-items-center p-6 text-center text-sm text-muted-foreground">{error}</div>
      )}
    </div>
  );
};

export default Live2DCanvas;
