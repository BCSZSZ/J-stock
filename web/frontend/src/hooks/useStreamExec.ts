import { useState, useCallback } from "react";
import { streamSSE } from "../api/client";

/** Hook for SSE-streamed command execution. */
export function useStreamExec() {
  const [lines, setLines] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [exitCode, setExitCode] = useState<number | null>(null);

  const execute = useCallback(
    async (path: string, body: Record<string, unknown>) => {
      setLines([]);
      setRunning(true);
      setExitCode(null);
      try {
        for await (const msg of streamSSE(path, body)) {
          if (msg.line !== undefined) {
            setLines((prev) => [...prev, msg.line!]);
          }
          if (msg.done) {
            setExitCode(msg.exit_code ?? -1);
          }
        }
      } catch (e) {
        setLines((prev) => [
          ...prev,
          `Error: ${e instanceof Error ? e.message : String(e)}`,
        ]);
        setExitCode(-1);
      } finally {
        setRunning(false);
      }
    },
    [],
  );

  const clear = useCallback(() => {
    setLines([]);
    setExitCode(null);
  }, []);

  return { lines, running, exitCode, execute, clear };
}
