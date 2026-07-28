import type { ReactNode } from "react";

export function Panel({ title, eyebrow, action, className = "", children }: {
  title: string;
  eyebrow?: string;
  action?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={`panel ${className}`}>
      <header><div>{eyebrow && <small>{eyebrow}</small>}<h2>{title}</h2></div>{action}</header>
      <div className="panel-body">{children}</div>
    </section>
  );
}
