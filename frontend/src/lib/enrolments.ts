// A class list as the API returns it (see backend/README.md).

export type ClassStudent = {
  id: string;
  admission_number: string;
  full_name: string;
  // Only for staff who may read student records; teachers do not get it.
  is_active?: boolean;
};

export type ClassList = {
  class: { id: string; academic_year_id: string; name: string };
  students: ClassStudent[];
};

// The API's limit for one "enrol" request.
export const MAX_ENROL_AT_ONCE = 100;
