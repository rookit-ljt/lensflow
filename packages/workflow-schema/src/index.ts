import { z } from "zod";

export const portDataTypeSchema = z.enum([
  "text",
  "image",
  "video",
  "audio",
  "json",
  "shot",
]);

export const workflowNodeSchema = z.object({
  id: z.string().min(1),
  type: z.string().min(1),
  version: z.string().min(1),
  position: z.object({ x: z.number(), y: z.number() }),
  config: z.record(z.string(), z.unknown()).default({}),
});

export const workflowEdgeSchema = z.object({
  id: z.string().min(1),
  source: z.string().min(1),
  sourceHandle: z.string().optional(),
  target: z.string().min(1),
  targetHandle: z.string().optional(),
});

export const productWorkflowSchema = z.object({
  schemaVersion: z.literal("1.0"),
  id: z.string().min(1),
  name: z.string().min(1),
  nodes: z.array(workflowNodeSchema),
  edges: z.array(workflowEdgeSchema),
  viewport: z
    .object({ x: z.number(), y: z.number(), zoom: z.number().positive() })
    .optional(),
});

export type PortDataType = z.infer<typeof portDataTypeSchema>;
export type WorkflowNode = z.infer<typeof workflowNodeSchema>;
export type WorkflowEdge = z.infer<typeof workflowEdgeSchema>;
export type ProductWorkflow = z.infer<typeof productWorkflowSchema>;

export interface NodePortDefinition {
  key: string;
  label: string;
  dataType: PortDataType;
  required?: boolean;
}

export interface NodeDefinition {
  type: string;
  version: string;
  title: string;
  category: "input" | "ai" | "media" | "control";
  inputs: NodePortDefinition[];
  outputs: NodePortDefinition[];
}
