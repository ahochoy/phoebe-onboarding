import { createContext, useContext, useMemo, useRef, useState, type ReactNode } from "react";
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
        if (
          active instanceof HTMLElement &&
          active !== document.body &&
          !active.closest("[role=dialog]")
        ) {
          opener.current = active;
        }
        setTarget({ docId, passage });
      },
      close: () => setTarget(null),
    }),
    [],
  );

  return (
    <ViewerContext.Provider value={viewer}>
      {children}
      <DocumentViewer target={target} onClose={viewer.close} returnFocusTo={opener} />
    </ViewerContext.Provider>
  );
}
