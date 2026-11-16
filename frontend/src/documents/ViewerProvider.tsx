import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { DocumentViewer } from "./DocumentViewer";
import type { Passage } from "./sections";

export interface Viewer {
  /** Opens a document. Passage offsets are code points into its full text. */
  open(docId: string, passage?: Passage): void;
  close(): void;
}

interface Target {
  docId: string;
  passage: Passage | undefined;
}

const ViewerContext = createContext<Viewer | null>(null);

export function useViewer(): Viewer {
  const viewer = useContext(ViewerContext);
  if (!viewer) throw new Error("useViewer must be used inside <ViewerProvider>");
  return viewer;
}

/** Renders its children plus the document viewer dialog. */
export function ViewerProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<Target | null>(null);
  const opener = useRef<HTMLElement | null>(null);
  const viewer = useMemo<Viewer>(
    () => ({
      open: (docId, passage) => {
        // Keep the first opener while the viewer is already open (e.g. a citation click inside it).
        const active = document.activeElement;
        const inViewer = active instanceof HTMLElement && active.closest("[role=dialog]") !== null;
        if (!inViewer) {
          // Safari and macOS Firefox do not focus a button on mouse click; then there is
          // no opener to return to, and an earlier one would be stale.
          opener.current =
            active instanceof HTMLElement && active !== document.body ? active : null;
        }
        setTarget({ docId, passage });
      },
      close: () => setTarget(null),
    }),
    [],
  );
  const restoreFocus = useCallback(() => {
    opener.current?.focus();
    // Used once: a later open must capture its own opener, never reuse this one.
    opener.current = null;
  }, []);

  return (
    <ViewerContext.Provider value={viewer}>
      {children}
      <DocumentViewer target={target} onClose={viewer.close} restoreFocus={restoreFocus} />
    </ViewerContext.Provider>
  );
}
