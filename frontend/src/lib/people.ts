// Shapes returned by the school's people endpoints (see backend/README.md).

export type Member = {
  id: string;
  role: string;
  is_active: boolean;
  user: { id: string; full_name: string; email: string };
};

export type InvitationSummary = {
  id: string;
  email: string;
  role: string;
  status: "pending" | "accepted" | "revoked" | "expired";
  created_at: string;
  expires_at: string;
};
