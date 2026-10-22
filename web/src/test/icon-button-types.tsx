import { IconButton } from '../components/IconButton';

export const namedIcon = <IconButton aria-label="打开导航">+</IconButton>;
// @ts-expect-error Icon-only controls must require an accessible label.
export const unnamedIcon = <IconButton>+</IconButton>;
