import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

/** Shared hook: fetches ticker→name map once, cached globally. */
export function useTickerNames() {
  const { data } = useQuery({
    queryKey: ["ticker-names"],
    queryFn: api.tickerNames,
    staleTime: Infinity,
  });
  return data ?? {};
}
