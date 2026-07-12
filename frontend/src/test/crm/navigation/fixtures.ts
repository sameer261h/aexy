/**
 * Shared fixtures for CRM navigation-shell tests (unit + e2e).
 */

export const CRM_NAV_ITEMS = [
  { href: "/crm", label: "Overview" },
  { href: "/crm/inbox", label: "Inbox" },
  { href: "/crm/activities", label: "Activities" },
  { href: "/crm/calendar", label: "Calendar" },
] as const;

export const CRM_ROUTES_RESOLVING_TO_APP = [
  "/crm",
  "/crm/inbox",
  "/crm/activities",
  "/crm/calendar",
  "/crm/agents",
  "/crm/agents/new",
  "/crm/automations",
  "/crm/automations/new",
  "/crm/settings",
  "/crm/settings/integrations",
  "/crm/onboarding",
  "/crm/some-object-slug",
  "/crm/some-object-slug/pipeline",
  "/crm/some-object-slug/some-record-id",
];

export const mockWorkspace = {
  id: "ws-1",
  name: "Test Workspace",
  slug: "test-ws",
  type: "engineering",
  avatar_url: null,
  owner_id: "test-user-123",
  member_count: 10,
  team_count: 2,
  is_active: true,
};

export const mockUser = {
  id: "test-user-123",
  name: "Test Developer",
  email: "test@example.com",
  avatar_url: "",
  onboarding_completed: true,
};

export const mockEffectiveAccess = {
  apps: { crm: { enabled: true } },
  applied_template_id: null,
  applied_template_name: null,
  has_custom_overrides: false,
  is_admin: true,
};

export const mockDashboardPreferences = {
  id: "pref-123",
  user_id: "test-user-123",
  preset_type: "admin",
  visible_widgets: [],
  widget_order: [],
  widget_sizes: {},
};
