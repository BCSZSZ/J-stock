import { useState } from "react";

interface Props {
  title: string;
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmDialog({
  title,
  message,
  onConfirm,
  onCancel,
}: Props) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-gray-900 border border-gray-700 rounded-lg p-6 max-w-md w-full shadow-xl">
        <h3 className="text-lg font-semibold text-yellow-400 mb-2">{title}</h3>
        <p className="text-gray-300 text-sm mb-6">{message}</p>
        <div className="flex justify-end gap-3">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm rounded bg-gray-700 hover:bg-gray-600 text-gray-300"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="px-4 py-2 text-sm rounded bg-red-600 hover:bg-red-500 text-white font-medium"
          >
            Confirm
          </button>
        </div>
      </div>
    </div>
  );
}

/** Hook to manage confirm dialog state. */
export function useConfirmDialog() {
  const [state, setState] = useState<{
    open: boolean;
    title: string;
    message: string;
    resolve: ((v: boolean) => void) | null;
  }>({ open: false, title: "", message: "", resolve: null });

  function confirm(title: string, message: string): Promise<boolean> {
    return new Promise((resolve) => {
      setState({ open: true, title, message, resolve });
    });
  }

  function handleConfirm() {
    state.resolve?.(true);
    setState((s) => ({ ...s, open: false }));
  }

  function handleCancel() {
    state.resolve?.(false);
    setState((s) => ({ ...s, open: false }));
  }

  const dialog = state.open ? (
    <ConfirmDialog
      title={state.title}
      message={state.message}
      onConfirm={handleConfirm}
      onCancel={handleCancel}
    />
  ) : null;

  return { confirm, dialog };
}
