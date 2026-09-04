import { Suspense } from "react";
import { ExceptionsScreen } from "@/components/exceptions-screen";

export default function ExceptionsPage() {
  return (
    <Suspense>
      <ExceptionsScreen />
    </Suspense>
  );
}
