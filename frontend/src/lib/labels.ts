// Plain-language names for the codes the API uses.

const ROLE_LABELS: Record<string, string> = {
  school_admin: "School administrator",
  principal: "Principal",
  teacher: "Teacher",
  finance_officer: "Finance officer",
  registrar: "Registrar",
  guardian: "Parent or guardian",
  student: "Student",
};

const PERMISSION_LABELS: Record<string, string> = {
  "members.read": "See the school's members",
  "members.manage": "Invite and remove members",
  "students.read": "See student records",
  "students.manage": "Add and change student records",
  "academics.read": "See the school year and terms",
  "academics.manage": "Set up school years and terms",
  "classes.read": "See every class and its class teachers",
  "classes.manage": "Set up classes and choose class teachers",
  "classes.read_own": "See the classes you teach",
  "enrolments.manage": "Add students to classes and move them",
  "attendance.read": "See every class's attendance",
  "attendance.record": "Take and correct any class's attendance",
  "attendance.record_own": "Take attendance for the classes you teach",
};

// Every role a school can give, in the order they are offered.
export const ROLES = Object.keys(ROLE_LABELS);

export function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role;
}

export function permissionLabel(permission: string): string {
  return PERMISSION_LABELS[permission] ?? permission;
}

const INVITATION_STATUS_LABELS: Record<string, string> = {
  pending: "Waiting",
  accepted: "Accepted",
  revoked: "Withdrawn",
  expired: "Expired",
};

export function invitationStatusLabel(status: string): string {
  return INVITATION_STATUS_LABELS[status] ?? status;
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" });
}
