import Link from "next/link";

export default function NotFound() {
  return (
    <main className="app-not-found">
      <div>
        <p className="app-not-found__code">404</p>
        <h1>页面不存在</h1>
        <p>项目可能已被删除，或者链接已经失效。</p>
        <Link href="/dashboard">返回项目列表</Link>
      </div>
    </main>
  );
}
