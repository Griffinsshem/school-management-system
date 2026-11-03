"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { AcademicYearList } from "@/lib/academic-years";

// The term to show: the one in the address, or else today's term (Term 1
// outside the terms), as on the results page. Null while it is looked up.
export function useTerm(): [number | null, (term: number) => void] {
  const searchParams = useSearchParams();
  const asked = Number(searchParams.get("term"));
  const [term, setTerm] = useState<number | null>(asked >= 1 && asked <= 3 ? asked : null);

  useEffect(() => {
    if (term !== null) {
      return;
    }
    let cancelled = false;
    api<AcademicYearList>("/school/academic-years").then((response) => {
      if (!cancelled) {
        setTerm(response.ok ? (response.data.current.term_number ?? 1) : 1);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [term]);

  return [term, setTerm];
}
