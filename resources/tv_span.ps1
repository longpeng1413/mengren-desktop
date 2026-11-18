
Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Runtime.InteropServices;
using System.Collections.Generic;
public class TvSpan {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [StructLayout(LayoutKind.Sequential)] public struct MONITORINFO { public int cbSize; public RECT rcMonitor; public RECT rcWork; public uint dwFlags; }
  public delegate bool MonEnumProc(IntPtr h, IntPtr hdc, ref RECT r, IntPtr d);
  public delegate bool WinEnumProc(IntPtr h, IntPtr p);
  [DllImport("user32.dll")] static extern bool EnumDisplayMonitors(IntPtr hdc, IntPtr clip, MonEnumProc cb, IntPtr d);
  [DllImport("user32.dll")] static extern bool GetMonitorInfo(IntPtr h, ref MONITORINFO mi);
  [DllImport("user32.dll")] static extern IntPtr MonitorFromWindow(IntPtr h, uint f);
  [DllImport("user32.dll")] static extern IntPtr SetThreadDpiAwarenessContext(IntPtr c);
  [DllImport("user32.dll")] static extern bool EnumWindows(WinEnumProc cb, IntPtr p);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] static extern bool IsZoomed(IntPtr h);
  [DllImport("user32.dll")] static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr h, int msg, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] static extern int GetWindowLong(IntPtr h, int i);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int w, int hh, uint f);
  [DllImport("dwmapi.dll")] static extern int DwmGetWindowAttribute(IntPtr h, int a, out RECT r, int s);

  static List<MONITORINFO> Monitors() {
    var list = new List<MONITORINFO>();
    EnumDisplayMonitors(IntPtr.Zero, IntPtr.Zero, delegate(IntPtr h, IntPtr hdc, ref RECT r, IntPtr d) {
      var mi = new MONITORINFO(); mi.cbSize = Marshal.SizeOf(typeof(MONITORINFO)); GetMonitorInfo(h, ref mi); list.Add(mi); return true;
    }, IntPtr.Zero);
    return list;
  }


  static RECT RowWorkArea(IntPtr hwnd) {
    var mi = new MONITORINFO(); mi.cbSize = Marshal.SizeOf(typeof(MONITORINFO));
    GetMonitorInfo(MonitorFromWindow(hwnd, 2), ref mi);
    RECT u = mi.rcWork;
    foreach (var m in Monitors()) {
      if (Math.Abs(m.rcMonitor.T - mi.rcMonitor.T) > 20) continue;
      u.L = Math.Min(u.L, m.rcWork.L); u.R = Math.Max(u.R, m.rcWork.R);
      u.T = Math.Max(u.T, m.rcWork.T); u.B = Math.Min(u.B, m.rcWork.B);
    }
    return u;
  }

  static void Place(IntPtr h, RECT t) {

    for (int i = 0; i < 4; i++) {
      RECT r, f; GetWindowRect(h, out r); DwmGetWindowAttribute(h, 9, out f, 16);
      int dl = f.L - r.L, dt = f.T - r.T, dr = r.R - f.R, db = r.B - f.B;
      if (i > 0 && f.L == t.L && f.T == t.T && f.R == t.R && f.B == t.B) return;
      SetWindowPos(h, IntPtr.Zero, t.L - dl, t.T - dt, (t.R - t.L) + dl + dr, (t.B - t.T) + dt + db, 0x0014);
      System.Threading.Thread.Sleep(250);
    }
  }

  public static List<string> Run(int[] pids) {
    SetThreadDpiAwarenessContext(new IntPtr(-4));
    var set = new HashSet<int>(pids); var wins = new List<IntPtr>(); var log = new List<string>();
    EnumWindows(delegate(IntPtr h, IntPtr p) {
      uint pid; GetWindowThreadProcessId(h, out pid);
      if (set.Contains((int)pid) && IsWindowVisible(h) && (GetWindowLong(h, -16) & 0x00C00000) == 0x00C00000) wins.Add(h);
      return true;
    }, IntPtr.Zero);
    foreach (var h in wins) {
      if (IsIconic(h)) continue;
      RECT t = RowWorkArea(h);
      if (IsZoomed(h)) {

        SendMessage(h, 0x0112, new IntPtr(0xF120), IntPtr.Zero);
        for (int k = 0; k < 20 && IsZoomed(h); k++) System.Threading.Thread.Sleep(100);
        System.Threading.Thread.Sleep(200);
        if (IsZoomed(h)) continue;
      }
      Place(h, t);
      RECT f; DwmGetWindowAttribute(h, 9, out f, 16);
      var s = new StringBuilder(256); GetWindowText(h, s, 256);
      log.Add(String.Format("{0} -> ({1},{2})-({3},{4})  ?? ({5},{6})-({7},{8})", s, f.L, f.T, f.R, f.B, t.L, t.T, t.R, t.B));
    }
    return log;
  }
}
"@
$guardDir = 'TradingView' + (-join @([char]0x94FA,[char]0x6EE1,[char]0x4E24,[char]0x5C4F))
$guardName = (-join @([char]0x53F3,[char]0x5C4F,[char]0x653E,[char]0x5927,[char]0x5B88,[char]0x62A4)) + '.exe'
$guard = Join-Path (Join-Path ([Environment]::GetFolderPath('MyDocuments')) $guardDir) $guardName
$p = Get-Process -Name TradingView -ErrorAction SilentlyContinue
if (-not $p) { Write-Error "TradingView is not running"; exit 1 }
if (Test-Path $guard) { Start-Process $guard }
$result = [TvSpan]::Run([int[]]($p.Id))
if (-not $result -or $result.Count -eq 0) { Write-Error "No usable TradingView window"; exit 1 }
$result
