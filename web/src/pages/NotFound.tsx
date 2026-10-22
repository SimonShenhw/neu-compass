import { Link } from 'react-router-dom';
import { EmptyState } from '../components/EmptyState';
export function NotFound() {
  return (
    <EmptyState action={<Link to="/">返回首页</Link>}>
      404 · 找不到这个页面
    </EmptyState>
  );
}
