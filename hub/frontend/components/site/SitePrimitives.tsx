"use client";

import React, { createContext, useContext, useState } from "react";
import clsx from "clsx";

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "outline" | "destructive";
  size?: "default" | "sm";
};

export function Button({ className, variant = "default", size = "default", ...props }: ButtonProps) {
  return <button className={clsx("cx-button", "site-button", `site-button-${variant}`, `site-button-${size}`, className)} {...props} />;
}

export function Input({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input className={clsx("site-input", className)} {...props} />;
}

type SliderProps = Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "defaultValue" | "onChange"> & {
  value?: number[];
  defaultValue?: number[];
  onValueChange?: (value: number[]) => void;
};

export function Slider({ value, defaultValue, onValueChange, className, min = 0, max = 100, step = 1, ...props }: SliderProps) {
  const current = value?.[0] ?? defaultValue?.[0] ?? Number(min);
  return <input type="range" className={clsx("site-slider", className)} value={current} min={min} max={max} step={step} onChange={(event) => onValueChange?.([Number(event.target.value)])} {...props} />;
}

type TabsState = { value: string; setValue: (value: string) => void };
const TabsContext = createContext<TabsState | null>(null);

export function Tabs({ defaultValue, className, children }: { defaultValue: string; className?: string; children: React.ReactNode }) {
  const [value, setValue] = useState(defaultValue);
  return <TabsContext.Provider value={{ value, setValue }}><div className={className}>{children}</div></TabsContext.Provider>;
}

export function TabsList({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={className} role="tablist">{children}</div>;
}

export function TabsTrigger({ value, className, children }: { value: string; className?: string; children: React.ReactNode }) {
  const tabs = useContext(TabsContext);
  const active = tabs?.value === value;
  return <button type="button" role="tab" data-state={active ? "active" : "inactive"} aria-selected={active} className={className} onClick={() => tabs?.setValue(value)}>{children}</button>;
}

export function TabsContent({ value, className, children }: { value: string; className?: string; children: React.ReactNode }) {
  const tabs = useContext(TabsContext);
  if (tabs?.value !== value) return null;
  return <div role="tabpanel" data-state="active" className={className}>{children}</div>;
}

export function Table({ className, ...props }: React.TableHTMLAttributes<HTMLTableElement>) { return <table className={className} {...props} />; }
export function TableHeader(props: React.HTMLAttributes<HTMLTableSectionElement>) { return <thead {...props} />; }
export function TableBody(props: React.HTMLAttributes<HTMLTableSectionElement>) { return <tbody {...props} />; }
export function TableRow(props: React.HTMLAttributes<HTMLTableRowElement>) { return <tr {...props} />; }
export function TableHead(props: React.ThHTMLAttributes<HTMLTableCellElement>) { return <th {...props} />; }
export function TableCell(props: React.TdHTMLAttributes<HTMLTableCellElement>) { return <td {...props} />; }

export function Switch({ checked = false, onCheckedChange, className, ...props }: Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "onChange"> & { checked?: boolean; onCheckedChange?: (checked: boolean) => void }) {
  return <button type="button" role="switch" aria-checked={checked} data-state={checked ? "checked" : "unchecked"} className={clsx("site-switch", className)} onClick={() => onCheckedChange?.(!checked)} {...props}><span /></button>;
}
