// Fixed demo source selection; expected visible output is imported by tests only.
import type { ProgramScenario } from './programsDemo';
export const programScenarios = {
  'cs-2025-stale': {
    view: 'curriculum',
    programId: 'cs-ms',
    curriculum: 'curriculum-cs-ms',
    selectedPlanId: 'cs-ms-boston-2025-2026-standard',
    policies: 'policies-cs-ms-2025-stale',
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {
      'cs-ms-boston-2026-2027-align':
        'ee94cf9b6d017da2ab494585d62dd3a6d6be952d696e991503503ae96533e786',
      'cs-ms-boston-2026-2027-bridge':
        '974b3a8bb7d77e49c1e2933d78e2756d53097feeab8ac5c73c78b779de9376fd',
      'cs-ms-boston-2026-2027-standard':
        'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
      'cs-ms-boston-2025-2026-standard':
        '8d769db5672591d0980041ff4f77764b0a1ab3b9b9c24ee650e1c675438acf71',
    },
  },
  'cs-404': {
    view: 'curriculum',
    programId: 'cs-ms',
    curriculum: 'curriculum-404',
    selectedPlanId: null,
    policies: null,
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {},
  },
  'cs-503': {
    view: 'curriculum',
    programId: 'cs-ms',
    curriculum: 'failure-503-transport',
    selectedPlanId: null,
    policies: null,
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {},
  },
  'cs-align-not-linked': {
    view: 'curriculum',
    programId: 'cs-ms',
    curriculum: 'curriculum-cs-ms',
    selectedPlanId: 'cs-ms-boston-2026-2027-align',
    policies: 'policies-cs-ms-align-not-linked',
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {
      'cs-ms-boston-2026-2027-align':
        'ee94cf9b6d017da2ab494585d62dd3a6d6be952d696e991503503ae96533e786',
      'cs-ms-boston-2026-2027-bridge':
        '974b3a8bb7d77e49c1e2933d78e2756d53097feeab8ac5c73c78b779de9376fd',
      'cs-ms-boston-2026-2027-standard':
        'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
      'cs-ms-boston-2025-2026-standard':
        '8d769db5672591d0980041ff4f77764b0a1ab3b9b9c24ee650e1c675438acf71',
    },
  },
  'cs-bad-plan': {
    view: 'curriculum',
    programId: 'cs-ms',
    curriculum: 'curriculum-cs-ms-bad-plan',
    selectedPlanId: null,
    policies: null,
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {
      'cs-ms-boston-2026-2027-align':
        'ee94cf9b6d017da2ab494585d62dd3a6d6be952d696e991503503ae96533e786',
      'cs-ms-boston-2026-2027-standard':
        'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
      'cs-ms-boston-2025-2026-standard':
        '8d769db5672591d0980041ff4f77764b0a1ab3b9b9c24ee650e1c675438acf71',
    },
  },
  'cs-bridge-draft': {
    view: 'curriculum',
    programId: 'cs-ms',
    curriculum: 'curriculum-cs-ms',
    selectedPlanId: 'cs-ms-boston-2026-2027-bridge',
    policies: 'policies-cs-ms-bridge-draft',
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {
      'cs-ms-boston-2026-2027-align':
        'ee94cf9b6d017da2ab494585d62dd3a6d6be952d696e991503503ae96533e786',
      'cs-ms-boston-2026-2027-bridge':
        '974b3a8bb7d77e49c1e2933d78e2756d53097feeab8ac5c73c78b779de9376fd',
      'cs-ms-boston-2026-2027-standard':
        'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
      'cs-ms-boston-2025-2026-standard':
        '8d769db5672591d0980041ff4f77764b0a1ab3b9b9c24ee650e1c675438acf71',
    },
  },
  'cs-duplicate-plan': {
    view: 'curriculum',
    programId: 'cs-ms',
    curriculum: 'curriculum-cs-ms-duplicate-plan',
    selectedPlanId: null,
    policies: null,
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {
      'cs-ms-boston-2026-2027-align':
        'ee94cf9b6d017da2ab494585d62dd3a6d6be952d696e991503503ae96533e786',
      'cs-ms-boston-2026-2027-bridge':
        '974b3a8bb7d77e49c1e2933d78e2756d53097feeab8ac5c73c78b779de9376fd',
      'cs-ms-boston-2026-2027-standard':
        'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
      'cs-ms-boston-2025-2026-standard':
        '8d769db5672591d0980041ff4f77764b0a1ab3b9b9c24ee650e1c675438acf71',
    },
  },
  'cs-duplicate-scope': {
    view: 'curriculum',
    programId: 'cs-ms',
    curriculum: 'curriculum-cs-ms-duplicate-scope',
    selectedPlanId: null,
    policies: null,
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {
      'cs-ms-boston-2026-2027-align':
        'ee94cf9b6d017da2ab494585d62dd3a6d6be952d696e991503503ae96533e786',
      'cs-ms-boston-2026-2027-bridge':
        '974b3a8bb7d77e49c1e2933d78e2756d53097feeab8ac5c73c78b779de9376fd',
      'cs-ms-boston-2026-2027-standard':
        'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
      'cs-ms-boston-2025-2026-standard':
        '8d769db5672591d0980041ff4f77764b0a1ab3b9b9c24ee650e1c675438acf71',
      'cs-ms-boston-2026-2027-standard-copy':
        '9e2988e79e1e327b9d135eeda25be25dfc64fa0ada32698a8b18cf496e05dac4',
    },
  },
  'cs-foreign-plan': {
    view: 'curriculum',
    programId: 'cs-ms',
    curriculum: 'curriculum-cs-ms-foreign-plan',
    selectedPlanId: null,
    policies: null,
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {
      'cs-ms-boston-2026-2027-align':
        'ee94cf9b6d017da2ab494585d62dd3a6d6be952d696e991503503ae96533e786',
      'cs-ms-boston-2026-2027-bridge':
        '974b3a8bb7d77e49c1e2933d78e2756d53097feeab8ac5c73c78b779de9376fd',
      'cs-ms-boston-2026-2027-standard':
        'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
      'cs-ms-boston-2025-2026-standard':
        '21c1643d4afa38cb0c4b428073e551dfdd07012e421f871d5eeec9d62c8c0e0c',
    },
  },
  'cs-malformed': {
    view: 'curriculum',
    programId: 'cs-ms',
    curriculum: 'curriculum-cs-ms-malformed',
    selectedPlanId: null,
    policies: null,
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {
      'cs-ms-boston-2026-2027-align':
        'ee94cf9b6d017da2ab494585d62dd3a6d6be952d696e991503503ae96533e786',
      'cs-ms-boston-2026-2027-bridge':
        '974b3a8bb7d77e49c1e2933d78e2756d53097feeab8ac5c73c78b779de9376fd',
      'cs-ms-boston-2026-2027-standard':
        'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
      'cs-ms-boston-2025-2026-standard':
        '8d769db5672591d0980041ff4f77764b0a1ab3b9b9c24ee650e1c675438acf71',
    },
  },
  'cs-no-plan-table': {
    view: 'curriculum',
    programId: 'cs-ms',
    curriculum: 'curriculum-cs-ms-no-plan-table',
    selectedPlanId: null,
    policies: null,
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {},
  },
  'cs-nothing-selected': {
    view: 'curriculum',
    programId: 'cs-ms',
    curriculum: 'curriculum-cs-ms',
    selectedPlanId: null,
    policies: null,
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {
      'cs-ms-boston-2026-2027-align':
        'ee94cf9b6d017da2ab494585d62dd3a6d6be952d696e991503503ae96533e786',
      'cs-ms-boston-2026-2027-bridge':
        '974b3a8bb7d77e49c1e2933d78e2756d53097feeab8ac5c73c78b779de9376fd',
      'cs-ms-boston-2026-2027-standard':
        'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
      'cs-ms-boston-2025-2026-standard':
        '8d769db5672591d0980041ff4f77764b0a1ab3b9b9c24ee650e1c675438acf71',
    },
  },
  'cs-plan-revised': {
    view: 'curriculum',
    programId: 'cs-ms',
    curriculum: 'curriculum-cs-ms',
    selectedPlanId: null,
    policies: null,
    planRevised: true,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {
      'cs-ms-boston-2026-2027-align':
        'ee94cf9b6d017da2ab494585d62dd3a6d6be952d696e991503503ae96533e786',
      'cs-ms-boston-2026-2027-bridge':
        '974b3a8bb7d77e49c1e2933d78e2756d53097feeab8ac5c73c78b779de9376fd',
      'cs-ms-boston-2026-2027-standard':
        'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
      'cs-ms-boston-2025-2026-standard':
        '8d769db5672591d0980041ff4f77764b0a1ab3b9b9c24ee650e1c675438acf71',
    },
  },
  'cs-selected-plan-gone': {
    view: 'curriculum',
    programId: 'cs-ms',
    curriculum: 'curriculum-cs-ms',
    selectedPlanId: 'cs-ms-boston-2030-2031-standard',
    policies: null,
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {
      'cs-ms-boston-2026-2027-align':
        'ee94cf9b6d017da2ab494585d62dd3a6d6be952d696e991503503ae96533e786',
      'cs-ms-boston-2026-2027-bridge':
        '974b3a8bb7d77e49c1e2933d78e2756d53097feeab8ac5c73c78b779de9376fd',
      'cs-ms-boston-2026-2027-standard':
        'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
      'cs-ms-boston-2025-2026-standard':
        '8d769db5672591d0980041ff4f77764b0a1ab3b9b9c24ee650e1c675438acf71',
    },
  },
  'cs-share-base-slashes': {
    view: 'curriculum',
    programId: 'cs-ms',
    curriculum: 'curriculum-cs-ms',
    selectedPlanId: null,
    policies: null,
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test//',
    planRevisions: {
      'cs-ms-boston-2026-2027-align':
        'ee94cf9b6d017da2ab494585d62dd3a6d6be952d696e991503503ae96533e786',
      'cs-ms-boston-2026-2027-bridge':
        '974b3a8bb7d77e49c1e2933d78e2756d53097feeab8ac5c73c78b779de9376fd',
      'cs-ms-boston-2026-2027-standard':
        'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
      'cs-ms-boston-2025-2026-standard':
        '8d769db5672591d0980041ff4f77764b0a1ab3b9b9c24ee650e1c675438acf71',
    },
  },
  'cs-standard-policies-404': {
    view: 'curriculum',
    programId: 'cs-ms',
    curriculum: 'curriculum-cs-ms',
    selectedPlanId: 'cs-ms-boston-2026-2027-standard',
    policies: 'policies-404',
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {
      'cs-ms-boston-2026-2027-align':
        'ee94cf9b6d017da2ab494585d62dd3a6d6be952d696e991503503ae96533e786',
      'cs-ms-boston-2026-2027-bridge':
        '974b3a8bb7d77e49c1e2933d78e2756d53097feeab8ac5c73c78b779de9376fd',
      'cs-ms-boston-2026-2027-standard':
        'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
      'cs-ms-boston-2025-2026-standard':
        '8d769db5672591d0980041ff4f77764b0a1ab3b9b9c24ee650e1c675438acf71',
    },
  },
  'cs-standard-policies-503': {
    view: 'curriculum',
    programId: 'cs-ms',
    curriculum: 'curriculum-cs-ms',
    selectedPlanId: 'cs-ms-boston-2026-2027-standard',
    policies: 'failure-503-transport',
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {
      'cs-ms-boston-2026-2027-align':
        'ee94cf9b6d017da2ab494585d62dd3a6d6be952d696e991503503ae96533e786',
      'cs-ms-boston-2026-2027-bridge':
        '974b3a8bb7d77e49c1e2933d78e2756d53097feeab8ac5c73c78b779de9376fd',
      'cs-ms-boston-2026-2027-standard':
        'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
      'cs-ms-boston-2025-2026-standard':
        '8d769db5672591d0980041ff4f77764b0a1ab3b9b9c24ee650e1c675438acf71',
    },
  },
  'cs-standard-policies-foreign-link': {
    view: 'curriculum',
    programId: 'cs-ms',
    curriculum: 'curriculum-cs-ms',
    selectedPlanId: 'cs-ms-boston-2026-2027-standard',
    policies: 'policies-foreign-link',
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {
      'cs-ms-boston-2026-2027-align':
        'ee94cf9b6d017da2ab494585d62dd3a6d6be952d696e991503503ae96533e786',
      'cs-ms-boston-2026-2027-bridge':
        '974b3a8bb7d77e49c1e2933d78e2756d53097feeab8ac5c73c78b779de9376fd',
      'cs-ms-boston-2026-2027-standard':
        'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
      'cs-ms-boston-2025-2026-standard':
        '8d769db5672591d0980041ff4f77764b0a1ab3b9b9c24ee650e1c675438acf71',
    },
  },
  'cs-standard-policies-other-plan': {
    view: 'curriculum',
    programId: 'cs-ms',
    curriculum: 'curriculum-cs-ms',
    selectedPlanId: 'cs-ms-boston-2026-2027-standard',
    policies: 'policies-other-plan',
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {
      'cs-ms-boston-2026-2027-align':
        'ee94cf9b6d017da2ab494585d62dd3a6d6be952d696e991503503ae96533e786',
      'cs-ms-boston-2026-2027-bridge':
        '974b3a8bb7d77e49c1e2933d78e2756d53097feeab8ac5c73c78b779de9376fd',
      'cs-ms-boston-2026-2027-standard':
        'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
      'cs-ms-boston-2025-2026-standard':
        '8d769db5672591d0980041ff4f77764b0a1ab3b9b9c24ee650e1c675438acf71',
    },
  },
  'cs-standard-policies-other-revision': {
    view: 'curriculum',
    programId: 'cs-ms',
    curriculum: 'curriculum-cs-ms',
    selectedPlanId: 'cs-ms-boston-2026-2027-standard',
    policies: 'policies-other-revision',
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {
      'cs-ms-boston-2026-2027-align':
        'ee94cf9b6d017da2ab494585d62dd3a6d6be952d696e991503503ae96533e786',
      'cs-ms-boston-2026-2027-bridge':
        '974b3a8bb7d77e49c1e2933d78e2756d53097feeab8ac5c73c78b779de9376fd',
      'cs-ms-boston-2026-2027-standard':
        'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
      'cs-ms-boston-2025-2026-standard':
        '8d769db5672591d0980041ff4f77764b0a1ab3b9b9c24ee650e1c675438acf71',
    },
  },
  'cs-standard-policies-review-changed': {
    view: 'curriculum',
    programId: 'cs-ms',
    curriculum: 'curriculum-cs-ms',
    selectedPlanId: 'cs-ms-boston-2026-2027-standard',
    policies: 'policies-review-changed',
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {
      'cs-ms-boston-2026-2027-align':
        'ee94cf9b6d017da2ab494585d62dd3a6d6be952d696e991503503ae96533e786',
      'cs-ms-boston-2026-2027-bridge':
        '974b3a8bb7d77e49c1e2933d78e2756d53097feeab8ac5c73c78b779de9376fd',
      'cs-ms-boston-2026-2027-standard':
        'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
      'cs-ms-boston-2025-2026-standard':
        '8d769db5672591d0980041ff4f77764b0a1ab3b9b9c24ee650e1c675438acf71',
    },
  },
  'cs-standard-policies-without-link': {
    view: 'curriculum',
    programId: 'cs-ms',
    curriculum: 'curriculum-cs-ms',
    selectedPlanId: 'cs-ms-boston-2026-2027-standard',
    policies: 'policies-ready-without-link',
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {
      'cs-ms-boston-2026-2027-align':
        'ee94cf9b6d017da2ab494585d62dd3a6d6be952d696e991503503ae96533e786',
      'cs-ms-boston-2026-2027-bridge':
        '974b3a8bb7d77e49c1e2933d78e2756d53097feeab8ac5c73c78b779de9376fd',
      'cs-ms-boston-2026-2027-standard':
        'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
      'cs-ms-boston-2025-2026-standard':
        '8d769db5672591d0980041ff4f77764b0a1ab3b9b9c24ee650e1c675438acf71',
    },
  },
  'cs-standard-ready': {
    view: 'curriculum',
    programId: 'cs-ms',
    curriculum: 'curriculum-cs-ms',
    selectedPlanId: 'cs-ms-boston-2026-2027-standard',
    policies: 'policies-cs-ms-standard-ready',
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {
      'cs-ms-boston-2026-2027-align':
        'ee94cf9b6d017da2ab494585d62dd3a6d6be952d696e991503503ae96533e786',
      'cs-ms-boston-2026-2027-bridge':
        '974b3a8bb7d77e49c1e2933d78e2756d53097feeab8ac5c73c78b779de9376fd',
      'cs-ms-boston-2026-2027-standard':
        'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
      'cs-ms-boston-2025-2026-standard':
        '8d769db5672591d0980041ff4f77764b0a1ab3b9b9c24ee650e1c675438acf71',
    },
  },
  'cs-standard-revision-unknown': {
    view: 'curriculum',
    programId: 'cs-ms',
    curriculum: 'curriculum-cs-ms',
    selectedPlanId: 'cs-ms-boston-2026-2027-standard',
    policies: 'policies-cs-ms-standard-ready',
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {
      'cs-ms-boston-2026-2027-align':
        'ee94cf9b6d017da2ab494585d62dd3a6d6be952d696e991503503ae96533e786',
      'cs-ms-boston-2026-2027-bridge':
        '974b3a8bb7d77e49c1e2933d78e2756d53097feeab8ac5c73c78b779de9376fd',
      'cs-ms-boston-2025-2026-standard':
        '8d769db5672591d0980041ff4f77764b0a1ab3b9b9c24ee650e1c675438acf71',
    },
  },
  'cs-standard-unavailable': {
    view: 'curriculum',
    programId: 'cs-ms',
    curriculum: 'curriculum-cs-ms',
    selectedPlanId: 'cs-ms-boston-2026-2027-standard',
    policies: 'policies-cs-ms-standard-unavailable',
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {
      'cs-ms-boston-2026-2027-align':
        'ee94cf9b6d017da2ab494585d62dd3a6d6be952d696e991503503ae96533e786',
      'cs-ms-boston-2026-2027-bridge':
        '974b3a8bb7d77e49c1e2933d78e2756d53097feeab8ac5c73c78b779de9376fd',
      'cs-ms-boston-2026-2027-standard':
        'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
      'cs-ms-boston-2025-2026-standard':
        '8d769db5672591d0980041ff4f77764b0a1ab3b9b9c24ee650e1c675438acf71',
    },
  },
  'cs-standard-unusable': {
    view: 'curriculum',
    programId: 'cs-ms',
    curriculum: 'curriculum-cs-ms',
    selectedPlanId: 'cs-ms-boston-2026-2027-standard',
    policies: 'policies-cs-ms-standard-unusable',
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {
      'cs-ms-boston-2026-2027-align':
        'ee94cf9b6d017da2ab494585d62dd3a6d6be952d696e991503503ae96533e786',
      'cs-ms-boston-2026-2027-bridge':
        '974b3a8bb7d77e49c1e2933d78e2756d53097feeab8ac5c73c78b779de9376fd',
      'cs-ms-boston-2026-2027-standard':
        'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
      'cs-ms-boston-2025-2026-standard':
        '8d769db5672591d0980041ff4f77764b0a1ab3b9b9c24ee650e1c675438acf71',
    },
  },
  'cs-text-edge': {
    view: 'curriculum',
    programId: 'cs-ms',
    curriculum: 'curriculum-cs-ms-text-edge',
    selectedPlanId: 'cs-ms-boston-2026-2027-align',
    policies: 'policies-cs-ms-align-text-edge',
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {
      'cs-ms-boston-2026-2027-align':
        'cc6920019b3cbbb79e132fefeb2945de035f6fc656b742b83f071c8c9c5feaad',
      'cs-ms-boston-2026-2027-bridge':
        '974b3a8bb7d77e49c1e2933d78e2756d53097feeab8ac5c73c78b779de9376fd',
      'cs-ms-boston-2026-2027-standard':
        'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
      'cs-ms-boston-2025-2026-standard':
        '8d769db5672591d0980041ff4f77764b0a1ab3b9b9c24ee650e1c675438acf71',
    },
  },
  'cs-unknown-requirement': {
    view: 'curriculum',
    programId: 'cs-ms',
    curriculum: 'curriculum-cs-ms-unknown-requirement',
    selectedPlanId: null,
    policies: null,
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {
      'cs-ms-boston-2026-2027-align':
        'ee94cf9b6d017da2ab494585d62dd3a6d6be952d696e991503503ae96533e786',
      'cs-ms-boston-2026-2027-bridge':
        '974b3a8bb7d77e49c1e2933d78e2756d53097feeab8ac5c73c78b779de9376fd',
      'cs-ms-boston-2026-2027-standard':
        'd99a2ba098fc258afcf26c976b827d57b711da6a83b1b0ee5ebf65861c7c5c7e',
      'cs-ms-boston-2025-2026-standard':
        '8d769db5672591d0980041ff4f77764b0a1ab3b9b9c24ee650e1c675438acf71',
    },
  },
  'ds-plan-selected': {
    view: 'curriculum',
    programId: 'ds-ms',
    curriculum: 'curriculum-ds-ms',
    selectedPlanId: 'ds-ms-boston-2026-2027-standard-ai',
    policies: 'policies-ds-ms-not-linked',
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {
      'ds-ms-boston-2026-2027-standard-ai':
        '852443e7c562b023a5fb374b0f056fa3dc3b1d6d0ef6728ba8fffce68d9cd5ee',
    },
  },
  'info-empty': {
    view: 'curriculum',
    programId: 'info-ms',
    curriculum: 'curriculum-info-ms',
    selectedPlanId: null,
    policies: null,
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {},
  },
  'list-429': {
    view: 'list',
    programs: 'failure-429',
  },
  'list-503': {
    view: 'list',
    programs: 'failure-503-transport',
  },
  'list-empty': {
    view: 'list',
    programs: 'programs-empty',
  },
  'list-malformed': {
    view: 'list',
    programs: 'programs-malformed',
  },
  'list-text-edge': {
    view: 'list',
    programs: 'programs-text-edge',
  },
  list: {
    view: 'list',
    programs: 'programs',
  },
  'pjm-no-plans': {
    view: 'curriculum',
    programId: 'pjm-ms',
    curriculum: 'curriculum-pjm-ms',
    selectedPlanId: null,
    policies: null,
    planRevised: false,
    publicBaseUrl: 'https://compass.example.test',
    planRevisions: {},
  },
} as const satisfies Record<string, ProgramScenario>;
