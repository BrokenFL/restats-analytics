import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { SubdivisionOption } from "../api";

type Props = {
  options: SubdivisionOption[];
  value: string;
  onChange: (value: string) => void;
};

export function SubdivisionCombobox({ options, value, onChange }: Props) {
  const listboxId = useId();
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [query, setQuery] = useState(value);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => setQuery(value), [value]);

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, []);

  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    const matches = normalized
      ? options.filter((option) => {
          const searchable = `${option.final_subdivision} ${option.city ?? ""}`.toLowerCase();
          return searchable.includes(normalized);
        })
      : options;
    return matches.slice(0, 40);
  }, [options, query]);

  useEffect(() => setActiveIndex(0), [query, options]);

  const commit = (nextValue: string) => {
    setQuery(nextValue);
    onChange(nextValue);
    setOpen(false);
  };

  return (
    <div className="subdivision-combobox" ref={rootRef}>
      <input
        id="subdivision"
        value={query}
        placeholder="Search subdivisions"
        autoComplete="off"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-activedescendant={open && filtered[activeIndex] ? `${listboxId}-${activeIndex}` : undefined}
        onFocus={() => setOpen(true)}
        onChange={(event) => {
          const next = event.target.value;
          setQuery(next);
          setOpen(true);
          if (!next) onChange("");
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setOpen(true);
            setActiveIndex((index) => Math.min(index + 1, Math.max(0, filtered.length - 1)));
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setActiveIndex((index) => Math.max(0, index - 1));
          } else if (event.key === "Enter" && open && filtered[activeIndex]) {
            event.preventDefault();
            commit(filtered[activeIndex].final_subdivision);
          } else if (event.key === "Escape") {
            setOpen(false);
          }
        }}
        onBlur={() => {
          window.setTimeout(() => {
            if (!options.some((option) => option.final_subdivision === query)) setQuery(value);
          }, 120);
        }}
      />
      {value ? (
        <button className="combobox-clear" type="button" aria-label="Clear subdivision" onClick={() => commit("")}>×</button>
      ) : null}
      {open ? (
        <ul className="combobox-list" id={listboxId} role="listbox">
          <li
            id={`${listboxId}-all`}
            role="option"
            aria-selected={!value}
            className={!value ? "selected" : ""}
            onPointerDown={(event) => event.preventDefault()}
            onClick={() => commit("")}
          >
            <span>All Subdivisions</span>
          </li>
          {filtered.map((option, index) => (
            <li
              key={`${option.final_subdivision}-${option.city ?? ""}`}
              id={`${listboxId}-${index}`}
              role="option"
              aria-selected={option.final_subdivision === value}
              className={`${index === activeIndex ? "active" : ""} ${option.final_subdivision === value ? "selected" : ""}`.trim()}
              onPointerDown={(event) => event.preventDefault()}
              onMouseEnter={() => setActiveIndex(index)}
              onClick={() => commit(option.final_subdivision)}
            >
              <span>{option.final_subdivision}</span>
              <small>{option.city ? `${option.city} · ` : ""}{option.count.toLocaleString()} records</small>
            </li>
          ))}
          {!filtered.length ? <li className="combobox-empty">No matching subdivisions</li> : null}
        </ul>
      ) : null}
    </div>
  );
}
