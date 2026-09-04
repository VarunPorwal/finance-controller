import { Suspense } from "react";
import { ExceptionsScreen } from "@/components/exceptions-screen";

export default async function ExceptionDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <Suspense>
      <ExceptionsScreen activeId={id} />
    </Suspense>
  );
}
