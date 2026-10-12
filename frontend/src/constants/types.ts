export type TaskResponse = {
  text: string;
  audio?: string;
  playback_finished?: boolean;
  /** Voice generation failed for this sentence; it is skipped so the pipeline keeps moving. */
  tts_failed?: boolean;
};

export type TaskStatus =
  | "created"
  | "llm_started"
  | "llm_finished"
  | "tts_finished"
  | "task_finished"
  | "pending_interruption"
  | "cancelled"

export type Task = {
  id: string;
  input?: string;
  response: TaskResponse[];
  status: TaskStatus;
  interruptionState?: {
    tts: boolean;
    llm: boolean;
    audio: boolean;
  };
};