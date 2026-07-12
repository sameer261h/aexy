import { Metadata } from "next";
import { AppAccessGuard } from "@/components/guards/AppAccessGuard";
import { CRMNav } from "@/components/crm/navigation/CRMNav";

export const metadata: Metadata = {
  title: "CRM",
};

export default function CRMLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <AppAccessGuard appId="crm">
      <CRMNav />
      {children}
    </AppAccessGuard>
  );
}
