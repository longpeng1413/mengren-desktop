using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

internal static class EnvironmentSwitch
{
    private const string ToolName = "Claude 环境切换";
    internal static readonly string StateDirectory = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "ClaudeEnvironmentSwitch");
    private static readonly string ZoneSnapshot = Path.Combine(StateDirectory, "DailyTimeZone.txt");
    private const string PacificZone = "Pacific Standard Time";

    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Length == 1 && args[0] == "--self-test") return SelfTest();
        if (args.Length != 1 || (args[0] != "--apply" && args[0] != "--restore")) return 2;
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        try
        {
            // Older desktop shortcuts use the same lock and snapshots.
            using (var mutex = new Mutex(false, @"Local\ClaudeEnvironmentSwitch"))
            {
                bool acquired;
                try { acquired = mutex.WaitOne(0); }
                catch (AbandonedMutexException) { acquired = true; }
                if (!acquired)
                    throw new InvalidOperationException("切换窗口已经打开，请先完成当前操作。");
                try { Switch(args[0] == "--apply"); }
                finally { mutex.ReleaseMutex(); }
            }
            return 0;
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, ToolName, MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return 1;
        }
    }

    private static void Switch(bool apply)
    {
        if (apply) CheckProxyListener();
        bool changed = ChangeEnvironment(apply, ZoneSnapshot, EdgeLanguageSwitch.HasSnapshot, CurrentZone, SetZone, EdgeLanguageSwitch.Apply);
        if (!changed) Notify("这台电脑当前没有待恢复的 Claude 环境。");
        else Notify(apply ? "已应用 Claude 环境。\n请使用已启用 Claude 分流配置的 Clash。" : "已恢复此电脑切换前的时区和 Edge 语言。");
    }

    private static bool ChangeEnvironment(bool apply, string stateFile, Func<bool> hasEdgeSnapshot,
        Func<string> readZone, Action<string> setZone, Action<bool> changeEdge)
    {
        var originalZone = readZone();
        var hasZoneSnapshot = File.Exists(stateFile);
        var legacySnapshot = hasEdgeSnapshot();
        if (!apply && !hasZoneSnapshot && !legacySnapshot) return false;
        var pairedZone = hasZoneSnapshot ? File.ReadAllText(stateFile).Trim()
            : legacySnapshot ? "China Standard Time" : originalZone;
        TimeZoneInfo.FindSystemTimeZoneById(pairedZone);
        if (apply && !hasZoneSnapshot)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(stateFile));
            var pending = stateFile + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                File.WriteAllText(pending, pairedZone, new UTF8Encoding(false));
                File.Move(pending, stateFile);
            }
            finally { if (File.Exists(pending)) File.Delete(pending); }
        }
        try
        {
            setZone(apply ? PacificZone : pairedZone);
            changeEdge(apply);
        }
        catch (Exception changeError)
        {
            try { setZone(originalZone); }
            catch (Exception restoreError)
            {
                throw new InvalidOperationException("环境切换失败，且时区回退未完成，请再次尝试恢复。",
                    new AggregateException(changeError, restoreError));
            }
            if (apply && !hasZoneSnapshot && !hasEdgeSnapshot()) File.Delete(stateFile);
            throw;
        }
        if (!apply && hasZoneSnapshot) File.Delete(stateFile);
        return true;
    }

    private static void CheckProxyListener()
    {
        var port = 7897;
        var destination = new Uri("https://claude.ai/");
        var local = WebRequest.GetSystemWebProxy().GetProxy(destination);
        if (local != null && local.IsLoopback) port = local.Port;
        else
        {
            using (var key = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Internet Settings"))
            {
                if (key != null && Equals(key.GetValue("ProxyEnable"), 1))
                {
                    var server = key.GetValue("ProxyServer") as string ?? "";
                    foreach (var item in server.Split(';'))
                    {
                        var parts = item.Split(new[] { '=' }, 2);
                        if (parts.Length == 2 && parts[0] != "https" && parts[0] != "http") continue;
                        var endpoint = parts[parts.Length - 1];
                        Uri address;
                        if (Uri.TryCreate("http://" + endpoint, UriKind.Absolute, out address) && address.IsLoopback)
                        {
                            port = address.Port;
                            if (parts.Length == 1 || parts[0] == "https") break;
                        }
                    }
                }
            }
        }
        using (var client = new TcpClient())
        {
            try
            {
                if (client.ConnectAsync("127.0.0.1", port).Wait(1000) && client.Connected) return;
            }
            catch (AggregateException) { }
        }
        throw new InvalidOperationException("没有找到正在监听的 Clash 本机代理。请先启动 Clash 并选中 Claude 分流配置。");
    }

    private static string CurrentZone()
    {
        TimeZoneInfo.ClearCachedData();
        return TimeZoneInfo.Local.Id;
    }

    private static void SetZone(string zone)
    {
        if (CurrentZone() == zone) return;
        var tool = Path.Combine(Environment.SystemDirectory, "tzutil.exe");
        using (var process = Process.Start(new ProcessStartInfo(tool, "/s \"" + zone + "\"") {
            UseShellExecute = false, CreateNoWindow = true
        }))
        {
            if (process == null || !process.WaitForExit(5000) || process.ExitCode != 0 || CurrentZone() != zone)
                throw new InvalidOperationException("Windows 未能确认时区切换。");
        }
    }

    private static void Notify(string message)
    {
        MessageBox.Show(message, ToolName, MessageBoxButtons.OK, MessageBoxIcon.Information);
    }

    private static int SelfTest()
    {
        var temp = Path.Combine(Path.GetTempPath(), "claude-switch-test-" + Guid.NewGuid().ToString("N"));
        var activeZone = "Tokyo Standard Time";
        bool edgeSnapshot = false;
        Func<string> read = () => activeZone;
        Action<string> write = value => activeZone = value;
        Action<bool> edge = value => edgeSnapshot = value;
        Func<bool> hasEdge = () => edgeSnapshot;
        try
        {
            if (ChangeEnvironment(false, temp, hasEdge, read, write, edge)) return 2;
            ChangeEnvironment(true, temp, hasEdge, read, write, edge);
            ChangeEnvironment(true, temp, hasEdge, read, write, edge);
            if (!edgeSnapshot || activeZone != PacificZone || File.ReadAllText(temp) != "Tokyo Standard Time") return 3;
            ChangeEnvironment(false, temp, hasEdge, read, write, edge);
            if (edgeSnapshot || activeZone != "Tokyo Standard Time" || File.Exists(temp)) return 4;
            try
            {
                ChangeEnvironment(true, temp, hasEdge, read, write, _ => { throw new IOException(); });
                return 5;
            }
            catch (IOException)
            {
                if (activeZone != "Tokyo Standard Time" || File.Exists(temp)) return 6;
            }
            return 0;
        }
        finally { if (File.Exists(temp)) File.Delete(temp); }
    }
}
