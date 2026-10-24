// Compile-time checks of a page's hand-written view types against the generated API types (R2b). The page's types
// are narrower on purpose (one shape per kind or status; every field the API always sends is required), so these
// helpers catch only the drift that matters. Only the type checker runs them (npm run typecheck).

// The keys of every member of a union, and a field's value in whichever members have it.
type Keys<T> = T extends unknown ? keyof T : never;
type Field<T, K extends PropertyKey> = T extends unknown
  ? K extends keyof T
    ? T[K]
    : never
  : never;
type Element<V> = V extends readonly (infer E)[] ? E : V;
type Scalar = string | number | boolean;
// The fields the page reads that the API lacks, or whose scalar values (or array elements) the API may send outside
// what the page accepts. Null is left out: the page may require a value where the API's type allows null but the
// API never sends it, and the page's own checks catch that at run time. Fields whose values are objects are passed
// over, so each object the page reads needs a check of its own.
export type Misfits<T, G> =
  | Exclude<Keys<T>, keyof G>
  | {
      [K in Keys<T> & keyof G]-?: [Element<NonNullable<G[K]>>] extends [Scalar]
        ? [Element<NonNullable<G[K]>>] extends [
            Element<NonNullable<Field<T, K>>>,
          ]
          ? never
          : K
        : never;
    }[Keys<T> & keyof G];
