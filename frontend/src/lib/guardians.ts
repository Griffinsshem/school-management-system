// Students' guardians as the API returns them (see backend/README.md).

import type { Me } from "@/lib/api";

export type Relationship = "mother" | "father" | "guardian" | "grandparent" | "sibling" | "other_relative";

// The only relationships the API accepts, in the order they are offered.
export const RELATIONSHIPS: { value: Relationship; label: string }[] = [
  { value: "mother", label: "Mother" },
  { value: "father", label: "Father" },
  { value: "guardian", label: "Guardian" },
  { value: "grandparent", label: "Grandparent" },
  { value: "sibling", label: "Sibling" },
  { value: "other_relative", label: "Other relative" },
];

export const MAX_GUARDIANS_PER_STUDENT = 4;
export const MAX_GUARDIAN_NAME = 200;
export const MAX_GUARDIAN_EMAIL = 254;
// Room for spaces and brackets in "(0712) 345 678"; the API checks the rest.
export const MAX_PHONE_INPUT = 25;

export type GuardianStudent = { id: string; admission_number: string; full_name: string };

export type Guardian = {
  id: string;
  full_name: string;
  phone: string; // "+254712345678"
  email: string | null;
};

export type LinkedGuardian = Guardian & { relationship: Relationship; is_primary: boolean };

export type StudentGuardians = { student: GuardianStudent; guardians: LinkedGuardian[] };

export type FoundGuardian = Guardian & { students: GuardianStudent[] };

export function canReadGuardians(me: Me): boolean {
  return me.permissions.includes("guardians.read");
}

export function canManageGuardians(me: Me): boolean {
  return me.permissions.includes("guardians.manage");
}

export function relationshipLabel(value: Relationship): string {
  return RELATIONSHIPS.find((r) => r.value === value)?.label ?? value;
}

// "+254712345678" shown as "0712 345 678", the way people in Kenya write it.
export function formatPhone(phone: string): string {
  const match = /^\+254(\d{3})(\d{3})(\d{3})$/.exec(phone);
  return match ? `0${match[1]} ${match[2]} ${match[3]}` : phone;
}
