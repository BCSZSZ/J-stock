/** Reusable terminal output display. */
interface Props {
  lines: string[];
  running: boolean;
  exitCode: number | null;
}

export default function LogOutput({ lines, running, exitCode }: Props) {
  return (
    <div className="bg-gray-950 border border-gray-800 rounded-lg p-4 font-mono text-xs max-h-96 overflow-y-auto">
      {lines.map((line, i) => (
        <div key={i} className="text-gray-300 whitespace-pre-wrap">
          {line}
        </div>
      ))}
      {running && (
        <div className="text-blue-400 animate-pulse mt-1">Running...</div>
      )}
      {exitCode !== null && (
        <div
          className={`mt-2 font-semibold ${exitCode === 0 ? "text-green-400" : "text-red-400"}`}
        >
          {exitCode === 0 ? "✓ Completed" : `✗ Exit code: ${exitCode}`}
        </div>
      )}
    </div>
  );
}
