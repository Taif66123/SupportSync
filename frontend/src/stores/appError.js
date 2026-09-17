import { create } from "zustand";

let nextId = 1;

/** Global error surface: any caught ApiError lands here and renders as a toast. */
export const useAppError = create((set) => ({
  errors: [],
  push(message, code = "error") {
    const id = nextId++;
    set((state) => ({ errors: [...state.errors, { id, code, message }] }));
    setTimeout(() => {
      set((state) => ({ errors: state.errors.filter((e) => e.id !== id) }));
    }, 6000);
  },
  dismiss(id) {
    set((state) => ({ errors: state.errors.filter((e) => e.id !== id) }));
  },
}));
