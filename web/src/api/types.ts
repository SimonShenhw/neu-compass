// The API's JSON shapes, generated from openapi.json into schema.ts (`npm run gen:api`). They say what the API
// promises, not what arrived: pages and hooks still check a response before they show it.
import type { components } from './schema';

export type Schemas = components['schemas'];
