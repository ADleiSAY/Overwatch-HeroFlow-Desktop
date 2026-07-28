export function Icon({ name }: { name: string }) {
  return <img className="icon" src={`/icons/${name}.svg`} aria-hidden="true" />;
}
