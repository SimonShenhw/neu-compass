import type { RequisiteNode } from '../components/RequisiteTree';

export type Course = {
  code: string;
  title: string;
  credits: number;
  year: string;
  description: string;
  fullDescription: string;
  topics: readonly string[];
  comparisonTopics?: readonly string[];
  prerequisite?: RequisiteNode;
  prerequisiteText: string;
  review: string;
};

export const courses: readonly Course[] = [
  {
    code: 'CS 5800',
    title: 'Algorithms',
    credits: 4,
    year: '2026–2027',
    description:
      'Presents the mathematical techniques used for the design and analysis of computer algorithms.',
    fullDescription:
      'Focuses on algorithmic design paradigms and techniques for analyzing correctness, time, and space complexity. Topics may include dynamic programming, graph algorithms, and NP-completeness.',
    topics: ['dynamic programming', 'graph algorithms', 'NP-completeness'],
    prerequisiteText: '目录没有列',
    review: '每周约 12 小时 · 难度 4 / 5',
  },
  {
    code: 'CS 6140',
    title: 'Machine Learning',
    credits: 4,
    year: '2026–2027',
    description:
      'Provides a broad look at a variety of techniques used in machine learning and data mining, and also examines issues associated with their use.',
    fullDescription:
      'Topics include supervised learning, decision tree induction, neural networks, instance-based learning, probabilistic methods, support vector machines, unsupervised learning, reinforcement learning, and data preprocessing.',
    topics: [
      'supervised learning',
      'decision tree induction',
      'neural networks',
      'instance-based learning',
      'probabilistic methods',
      'support vector machines',
      'unsupervised learning',
      'reinforcement learning',
      'data preprocessing',
    ],
    comparisonTopics: [
      'supervised learning',
      'neural networks',
      'reinforcement learning',
    ],
    prerequisite: {
      kind: 'any',
      children: [
        {
          kind: 'course',
          code: 'CS 5800',
          title: 'Algorithms',
          minimumGrade: 'C-',
        },
        {
          kind: 'course',
          code: 'CS 7800',
          title: 'Advanced Algorithms',
          minimumGrade: 'C-',
        },
      ],
    },
    prerequisiteText: 'CS 5800 或 CS 7800（最低 C-）',
    review: '没有足够数据',
  },
  {
    code: 'CS 7800',
    title: 'Advanced Algorithms',
    credits: 4,
    year: '2026–2027',
    description:
      'Examines advanced algorithms and techniques for the design and analysis of algorithms.',
    fullDescription:
      'This is fixture text for navigating a prerequisite leaf, not an independently verified catalog record.',
    topics: ['algorithm design', 'algorithm analysis'],
    prerequisiteText: '本原型未建模，要求未知',
    review: '没有足够数据',
  },
  {
    code: 'DS 5220',
    title: 'Supervised Machine Learning and Learning Theory',
    credits: 4,
    year: '2026–2027',
    description:
      'Introduces supervised machine learning, which is the study and design of algorithms that enable computers/machines to learn from experience or data.',
    fullDescription:
      'An illustrative excerpt used only to lay out this prototype. Refer to the official catalog for a complete rule.',
    topics: ['supervised learning', 'learning theory'],
    prerequisiteText: '目录没有列',
    review: '没有足够数据',
  },
  {
    code: 'CS 5100',
    title: 'Foundations of Artificial Intelligence',
    credits: 4,
    year: '2026–2027',
    description:
      'Introduces the fundamental problems, theories, and algorithms of the artificial intelligence field.',
    fullDescription:
      'Topics include heuristic search, planning, and an introduction to machine learning. This is fixture text, not a complete catalog entry.',
    topics: ['heuristic search', 'planning', 'machine learning'],
    prerequisiteText: '目录没有列',
    review: '没有足够数据',
  },
];

export const answerCodes = [
  'CS 6140',
  'DS 5220',
  'CS 5100',
  'CS 5800',
] as const;
export const comparisonCodes = [
  'CS 5800',
  'CS 6140',
  'DS 5220',
  'CS 5100',
] as const;
export const initialQuestion = '想先修一门机器学习，刚入学的 MSCS 可以选哪门？';
export const exampleQuestions = [
  'CS 5800 讲什么？',
  '适合入门的机器学习课',
  'CS 6140 的先修是什么？',
  'MSCS 第一学期一般选什么？',
] as const;
export const projectOptions = [
  { value: 'none', label: '不指定' },
  { value: 'cs-ms', label: 'MSCS' },
];
export const planOptions = [
  { value: 'none', label: '不指定' },
  { value: 'boston-2026', label: 'Boston · 2026–2027 · 普通 MS' },
];

export function findCourse(code: string) {
  return courses.find((course) => course.code === code);
}
export function coursePath(code: string) {
  return `/course/${encodeURIComponent(code.replaceAll(' ', '-'))}`;
}
export function codeFromPath(value: string) {
  return value.replaceAll('-', ' ');
}
