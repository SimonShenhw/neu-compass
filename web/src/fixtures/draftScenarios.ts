// Fixed demo source selection for /programs-draft-demo; the expected visible output is imported by tests only.
import type { DraftScenario } from './draftDemo';
export const draftScenarios = {
  'align-empty': {
    plan: { fixture: 'plans-cs-ms', plan_id: 'cs-ms-boston-2026-2027-align' },
    planContentSha256:
      'ee94cf9b6d017da2ab494585d62dd3a6d6be952d696e991503503ae96533e786',
    answer: 'draft-align-empty',
    status: 'idle',
    failure: null,
  },
  'align-mixed': {
    plan: { fixture: 'plans-cs-ms', plan_id: 'cs-ms-boston-2026-2027-align' },
    planContentSha256:
      'ee94cf9b6d017da2ab494585d62dd3a6d6be952d696e991503503ae96533e786',
    answer: 'draft-align-mixed',
    status: 'idle',
    failure: null,
  },
  'bridge-not-checked': {
    plan: { fixture: 'plans-cs-ms', plan_id: 'cs-ms-boston-2026-2027-bridge' },
    planContentSha256:
      '974b3a8bb7d77e49c1e2933d78e2756d53097feeab8ac5c73c78b779de9376fd',
    answer: null,
    status: 'idle',
    failure: null,
  },
  'ds-mixed': {
    plan: {
      fixture: 'plans-ds-ms',
      plan_id: 'ds-ms-boston-2026-2027-standard-ai',
    },
    planContentSha256:
      '852443e7c562b023a5fb374b0f056fa3dc3b1d6d0ef6728ba8fffce68d9cd5ee',
    answer: 'draft-ds-mixed',
    status: 'idle',
    failure: null,
  },
  'older-add': {
    plan: {
      fixture: 'plans-cs-ms',
      plan_id: 'cs-ms-boston-2025-2026-standard',
    },
    planContentSha256:
      '8d769db5672591d0980041ff4f77764b0a1ab3b9b9c24ee650e1c675438acf71',
    answer: 'draft-older-add',
    status: 'idle',
    failure: null,
  },
  'standard-404': {
    plan: {
      fixture: 'plans-cs-ms',
      plan_id: 'cs-ms-boston-2026-2027-standard',
    },
    planContentSha256:
      'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
    answer: null,
    status: 'idle',
    failure: 'draft-404',
  },
  'standard-409-unavailable': {
    plan: {
      fixture: 'plans-cs-ms',
      plan_id: 'cs-ms-boston-2026-2027-standard',
    },
    planContentSha256:
      'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
    answer: 'draft-standard-add',
    status: 'idle',
    failure: 'draft-409-unavailable',
  },
  'standard-422': {
    plan: {
      fixture: 'plans-cs-ms',
      plan_id: 'cs-ms-boston-2026-2027-standard',
    },
    planContentSha256:
      'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
    answer: null,
    status: 'idle',
    failure: 'draft-422',
  },
  'standard-429': {
    plan: {
      fixture: 'plans-cs-ms',
      plan_id: 'cs-ms-boston-2026-2027-standard',
    },
    planContentSha256:
      'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
    answer: null,
    status: 'idle',
    failure: 'failure-429',
  },
  'standard-502-unreadable': {
    plan: {
      fixture: 'plans-cs-ms',
      plan_id: 'cs-ms-boston-2026-2027-standard',
    },
    planContentSha256:
      'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
    answer: null,
    status: 'idle',
    failure: 'failure-502-unreadable',
  },
  'standard-503-transport': {
    plan: {
      fixture: 'plans-cs-ms',
      plan_id: 'cs-ms-boston-2026-2027-standard',
    },
    planContentSha256:
      'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
    answer: 'draft-standard-add',
    status: 'idle',
    failure: 'failure-503-transport',
  },
  'standard-504-timeout': {
    plan: {
      fixture: 'plans-cs-ms',
      plan_id: 'cs-ms-boston-2026-2027-standard',
    },
    planContentSha256:
      'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
    answer: null,
    status: 'idle',
    failure: 'failure-504-timeout',
  },
  'standard-add': {
    plan: {
      fixture: 'plans-cs-ms',
      plan_id: 'cs-ms-boston-2026-2027-standard',
    },
    planContentSha256:
      'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
    answer: 'draft-standard-add',
    status: 'idle',
    failure: null,
  },
  'standard-all-present': {
    plan: {
      fixture: 'plans-cs-ms',
      plan_id: 'cs-ms-boston-2026-2027-standard',
    },
    planContentSha256:
      'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
    answer: 'draft-standard-all-present',
    status: 'idle',
    failure: null,
  },
  'standard-checking-again': {
    plan: {
      fixture: 'plans-cs-ms',
      plan_id: 'cs-ms-boston-2026-2027-standard',
    },
    planContentSha256:
      'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
    answer: 'draft-standard-add',
    status: 'checking',
    failure: null,
  },
  'standard-checking-first': {
    plan: {
      fixture: 'plans-cs-ms',
      plan_id: 'cs-ms-boston-2026-2027-standard',
    },
    planContentSha256:
      'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
    answer: null,
    status: 'checking',
    failure: null,
  },
  'standard-empty': {
    plan: {
      fixture: 'plans-cs-ms',
      plan_id: 'cs-ms-boston-2026-2027-standard',
    },
    planContentSha256:
      'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
    answer: 'draft-standard-empty',
    status: 'idle',
    failure: null,
  },
  'standard-full': {
    plan: {
      fixture: 'plans-cs-ms',
      plan_id: 'cs-ms-boston-2026-2027-standard',
    },
    planContentSha256:
      'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
    answer: 'draft-standard-full',
    status: 'idle',
    failure: null,
  },
  'standard-invalid-many': {
    plan: {
      fixture: 'plans-cs-ms',
      plan_id: 'cs-ms-boston-2026-2027-standard',
    },
    planContentSha256:
      'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
    answer: 'draft-standard-invalid-many',
    status: 'idle',
    failure: null,
  },
  'standard-malformed': {
    plan: {
      fixture: 'plans-cs-ms',
      plan_id: 'cs-ms-boston-2026-2027-standard',
    },
    planContentSha256:
      'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
    answer: 'draft-malformed',
    status: 'idle',
    failure: null,
  },
  'standard-mixed': {
    plan: {
      fixture: 'plans-cs-ms',
      plan_id: 'cs-ms-boston-2026-2027-standard',
    },
    planContentSha256:
      'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
    answer: 'draft-standard-mixed',
    status: 'idle',
    failure: null,
  },
  'standard-nothing-new': {
    plan: {
      fixture: 'plans-cs-ms',
      plan_id: 'cs-ms-boston-2026-2027-standard',
    },
    planContentSha256:
      'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
    answer: 'draft-standard-nothing-new',
    status: 'idle',
    failure: null,
  },
  'standard-notices': {
    plan: {
      fixture: 'plans-cs-ms',
      plan_id: 'cs-ms-boston-2026-2027-standard',
    },
    planContentSha256:
      'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
    answer: 'draft-standard-notices',
    status: 'idle',
    failure: null,
  },
  'standard-other-revision': {
    plan: {
      fixture: 'plans-cs-ms',
      plan_id: 'cs-ms-boston-2026-2027-standard',
    },
    planContentSha256:
      'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
    answer: 'draft-other-revision',
    status: 'idle',
    failure: null,
  },
  'standard-over-limit': {
    plan: {
      fixture: 'plans-cs-ms',
      plan_id: 'cs-ms-boston-2026-2027-standard',
    },
    planContentSha256:
      'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
    answer: 'draft-standard-over-limit',
    status: 'idle',
    failure: null,
  },
  'standard-records-changed': {
    plan: {
      fixture: 'plans-cs-ms',
      plan_id: 'cs-ms-boston-2026-2027-standard',
    },
    planContentSha256:
      'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
    answer: 'draft-standard-records-changed',
    status: 'idle',
    failure: null,
  },
  'standard-text-edge': {
    plan: {
      fixture: 'plans-cs-ms',
      plan_id: 'cs-ms-boston-2026-2027-standard',
    },
    planContentSha256:
      'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
    answer: 'draft-text-edge',
    status: 'idle',
    failure: null,
  },
  'standard-text-input': {
    plan: {
      fixture: 'plans-cs-ms',
      plan_id: 'cs-ms-boston-2026-2027-standard',
    },
    planContentSha256:
      'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
    answer: 'draft-standard-text-input',
    status: 'idle',
    failure: null,
  },
  'standard-too-many': {
    plan: {
      fixture: 'plans-cs-ms',
      plan_id: 'cs-ms-boston-2026-2027-standard',
    },
    planContentSha256:
      'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
    answer: 'draft-standard-too-many',
    status: 'idle',
    failure: null,
  },
} as const satisfies Record<string, DraftScenario>;
