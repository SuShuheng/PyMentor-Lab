import "@pymentor/ui/styles.css";
import "./index.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { AdminRoutes } from "./admin-routes";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 15_000 },
  },
});

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root element");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AdminRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
