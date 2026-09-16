import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi, beforeEach } from "vitest";

afterEach(() => {
  cleanup();
});

const mockFetch = vi.fn();
Object.defineProperty(globalThis, "fetch", { value: mockFetch, writable: true });

const store: Record<string, string> = {};
const mockStorage = {
  getItem: (key: string) => store[key] ?? null,
  setItem: (key: string, value: string) => { store[key] = value; },
  removeItem: (key: string) => { delete store[key]; },
  clear: () => { Object.keys(store).forEach((k) => delete store[k]); },
  get length() { return Object.keys(store).length; },
  key: (index: number) => Object.keys(store)[index] ?? null,
};
Object.defineProperty(globalThis, "localStorage", { value: mockStorage, writable: true });

beforeEach(() => {
  mockFetch.mockReset();
  localStorage.clear();
});

export { mockFetch };
