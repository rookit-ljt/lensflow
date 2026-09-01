import {
  BaseEdge,
  getBezierPath,
  type EdgeProps,
  type EdgeTypes,
} from "@xyflow/react";

function StudioEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerStart,
  markerEnd,
  style,
  interactionWidth,
  selected,
  animated,
}: EdgeProps) {
  const [path] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  });

  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerStart={markerStart}
        markerEnd={markerEnd}
        interactionWidth={interactionWidth}
        style={style}
        className={`studio-edge__base ${selected ? "studio-edge__base--selected" : ""}`}
      />
      <path
        d={path}
        pathLength={1}
        vectorEffect="non-scaling-stroke"
        className={`studio-edge__glow ${selected ? "studio-edge__glow--selected" : ""} ${animated ? "studio-edge__glow--busy" : ""}`}
        aria-hidden="true"
      />
    </>
  );
}

export const edgeTypes: EdgeTypes = { studio: StudioEdge };
