// Server component layout для принудительного динамического рендеринга
export const dynamic = 'force-dynamic';
export const dynamicParams = true;
export const revalidate = 0;

export default function DashboardPageLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}

