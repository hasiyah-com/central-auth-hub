import { act, render } from "@testing-library/react";
import { IdleSessionGuard } from "../IdleSessionGuard";

describe("IdleSessionGuard", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    window.localStorage.clear();
  });

  afterEach(() => {
    jest.useRealTimers();
    jest.restoreAllMocks();
  });

  test("background time without user interaction revokes the session", async () => {
    const onExpire = jest.fn().mockResolvedValue(undefined);
    window.localStorage.setItem("hub:last-user-activity", String(Date.now()));
    render(<IdleSessionGuard timeoutMs={30_000} onExpire={onExpire} />);

    await act(async () => {
      jest.advanceTimersByTime(40_000);
    });

    expect(onExpire).toHaveBeenCalledTimes(1);
  });

  test("real user activity resets the idle window", async () => {
    const onExpire = jest.fn().mockResolvedValue(undefined);
    window.localStorage.setItem("hub:last-user-activity", String(Date.now()));
    render(<IdleSessionGuard timeoutMs={30_000} onExpire={onExpire} />);

    act(() => {
      jest.advanceTimersByTime(20_000);
      document.dispatchEvent(new MouseEvent("mousemove"));
      jest.advanceTimersByTime(20_000);
    });

    expect(onExpire).not.toHaveBeenCalled();
  });
});
