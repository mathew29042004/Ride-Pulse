/** Props that make a clickable table row usable from the keyboard (Tab to it, Enter or Space). */
export function rowLink(onActivate: () => void) {
  return {
    onClick: onActivate,
    tabIndex: 0,
    role: "link" as const,
    onKeyDown: (e: { key: string; preventDefault: () => void }) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onActivate();
      }
    },
  };
}
