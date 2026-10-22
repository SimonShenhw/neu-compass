import * as RadixSelect from '@radix-ui/react-select';
import { Check, ChevronDown, ChevronUp } from 'lucide-react';
import { useId } from 'react';
import styles from './Select.module.css';

export type SelectOption = { value: string; label: string };
export function Select({
  label,
  value,
  onChange,
  options,
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: readonly SelectOption[];
  disabled?: boolean;
}) {
  const labelId = useId();
  const valueId = useId();
  return (
    <RadixSelect.Root
      value={value}
      onValueChange={onChange}
      disabled={disabled}
    >
      <RadixSelect.Trigger
        className={styles.trigger}
        aria-labelledby={`${labelId} ${valueId}`}
      >
        <span id={labelId} className={styles.label}>
          {label}
        </span>
        <span id={valueId}>
          <RadixSelect.Value />
        </span>
        <RadixSelect.Icon>
          <ChevronDown aria-hidden="true" />
        </RadixSelect.Icon>
      </RadixSelect.Trigger>
      <RadixSelect.Portal>
        <RadixSelect.Content
          className={styles.content}
          position="popper"
          sideOffset={6}
        >
          <RadixSelect.ScrollUpButton className={styles.scroll}>
            <ChevronUp aria-hidden="true" />
          </RadixSelect.ScrollUpButton>
          <RadixSelect.Viewport>
            {options.map((option) => (
              <RadixSelect.Item
                className={styles.item}
                value={option.value}
                key={option.value}
              >
                <RadixSelect.ItemText>{option.label}</RadixSelect.ItemText>
                <RadixSelect.ItemIndicator>
                  <Check aria-hidden="true" />
                </RadixSelect.ItemIndicator>
              </RadixSelect.Item>
            ))}
          </RadixSelect.Viewport>
          <RadixSelect.ScrollDownButton className={styles.scroll}>
            <ChevronDown aria-hidden="true" />
          </RadixSelect.ScrollDownButton>
        </RadixSelect.Content>
      </RadixSelect.Portal>
    </RadixSelect.Root>
  );
}
