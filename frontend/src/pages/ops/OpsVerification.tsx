import { useQuery } from "@tanstack/react-query";
import { FileCheck } from "lucide-react";

import { Card, EmptyState, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import type { DriverDocument } from "@/lib/types";

import { DocumentRow } from "./DocumentReview";

export default function OpsVerification() {
  const queue = useQuery({
    queryKey: ["verification"],
    queryFn: () => api.get<DriverDocument[]>("drivers/verification-queue/"),
    refetchInterval: 15_000,
  });
  return (
    <>
      <PageHeader title="Driver verification" subtitle="Documents waiting for review, oldest first. Drivers are activated automatically once every required document is approved." />
      <Card>
        <div className="divide-y divide-line">
          {queue.data?.length === 0 && (
            <EmptyState icon={<FileCheck />} title="Queue is empty">
              New driver documents will appear here.
            </EmptyState>
          )}
          {(queue.data ?? []).map((doc) => (
            <DocumentRow key={doc.id} doc={doc} driverName={doc.driver_name} driverId={doc.driver} />
          ))}
        </div>
      </Card>
    </>
  );
}
