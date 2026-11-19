using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Management;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;

internal static class EdgeLanguageSwitch
{
    private static readonly string EdgePath = FindEdge();
    private static readonly string UserData = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "Microsoft", "Edge", "User Data");
    private static readonly string StatePath = Path.Combine(UserData, "Local State");
    private static readonly string SnapshotPath = Path.Combine(
        EnvironmentSwitch.StateDirectory, "DailyEdgeLanguage.json");
    private static readonly JavaScriptSerializer Json = new JavaScriptSerializer
    {
        MaxJsonLength = int.MaxValue,
        RecursionLimit = 256
    };
    private const string Us = "en-US";
    private const string UsLanguages = "en-US,en";

    internal static bool HasSnapshot() { return File.Exists(SnapshotPath); }

    private static string FindEdge()
    {
        foreach (var folder in new[] {
            Environment.SpecialFolder.ProgramFilesX86, Environment.SpecialFolder.ProgramFiles,
            Environment.SpecialFolder.LocalApplicationData })
        {
            var root = Environment.GetFolderPath(folder);
            if (String.IsNullOrEmpty(root)) continue;
            var path = Path.Combine(root, "Microsoft", "Edge", "Application", "msedge.exe");
            if (File.Exists(path)) return path;
        }
        return null;
    }

    private static string SelectedProfile(Dictionary<string, object> state)
    {
        var profile = StringValue(Dictionary(state, "profile"), "last_used") ?? "Default";
        if (!Regex.IsMatch(profile, @"\A(?:Default|Profile [0-9]+)\z"))
            throw new InvalidOperationException("当前 Edge 配置不支持自动切换，请切到常用配置再试。");
        return profile;
    }

    internal static void Apply(bool american)
    {
        bool hasSnapshot = File.Exists(SnapshotPath);
        if (!american && !hasSnapshot)
            return;
        if (!File.Exists(EdgePath) || !File.Exists(StatePath))
            throw new InvalidOperationException("请先在这台电脑上打开一次 Microsoft Edge。");

        var preflightState = Read(StatePath);
        var selected = SelectedProfile(preflightState);
        var snapshot = hasSnapshot ? Read(SnapshotPath) : null;
        var profile = snapshot == null ? selected : StringValue(snapshot, "profile") ?? "Default";
        if (!Regex.IsMatch(profile, @"\A(?:Default|Profile [0-9]+)\z"))
            throw new InvalidOperationException("保存的 Edge 配置无效。");
        if (american && selected != profile)
            throw new InvalidOperationException("请先恢复上一次切换的 Edge 配置，再切换当前配置。");
        var preferencesPath = Path.Combine(UserData, profile, "Preferences");
        if (!File.Exists(preferencesPath))
            throw new InvalidOperationException("找不到要切换的 Edge 配置。");

        var old = snapshot ?? CurrentLanguages(preflightState, Read(preferencesPath));
        var desired = american
            ? new Dictionary<string, object> { { "locale", Us }, { "accept", UsLanguages }, { "selected", UsLanguages } }
            : old;

        if (hasSnapshot && american && Same(CurrentLanguages(preflightState, Read(preferencesPath)), desired)
            && RunningEdge().Length > 0)
            return;

        bool wasOpen = CloseEdge();
        string oldStateText = File.ReadAllText(StatePath);
        string oldPreferencesText = File.ReadAllText(preferencesPath);
        var state = Json.Deserialize<Dictionary<string, object>>(oldStateText);
        var prefs = Json.Deserialize<Dictionary<string, object>>(oldPreferencesText);
        if (SelectedProfile(state) != selected)
        {
            if (wasOpen) Launch(false, null, selected);
            throw new InvalidOperationException("常用 Edge 配置在切换过程中发生了变化。");
        }
        if (!hasSnapshot)
        {
            var original = CurrentLanguages(state, prefs);
            original["profile"] = profile;
            Write(SnapshotPath, Json.Serialize(original));
        }

        var previousLocale = StringValue(GetOrCreateIntl(state), "app_locale");
        bool changedState = false;
        bool changedPrefs = false;
        try
        {
            var prefsIntl = GetOrCreateIntl(prefs);
            var stateIntl = GetOrCreateIntl(state);
            Set(prefsIntl, "accept_languages", desired["accept"]);
            Set(prefsIntl, "selected_languages", desired["selected"]);
            Set(stateIntl, "app_locale", desired["locale"]);
            if (RunningEdge().Length != 0)
                throw new InvalidOperationException("Edge 已重新打开，请关闭后重试。");
            Write(preferencesPath, Json.Serialize(prefs));
            changedPrefs = true;
            Write(StatePath, Json.Serialize(state));
            changedState = true;
            if (!Same(CurrentLanguages(Read(StatePath), Read(preferencesPath)), desired))
                throw new InvalidOperationException("Edge 语言配置没有保存完整。");
            if (wasOpen)
                Launch(american, StringValue(desired, "locale"), selected);
        }
        catch
        {
            if (RunningEdge().Length == 0)
            {
                if (changedState) Write(StatePath, oldStateText);
                if (changedPrefs) Write(preferencesPath, oldPreferencesText);
                if (!hasSnapshot) File.Delete(SnapshotPath);
                if (wasOpen) Launch(hasSnapshot, previousLocale, selected);
            }
            throw;
        }
        if (!american)
            File.Delete(SnapshotPath);
    }

    private static Process[] RunningEdge()
    {
        int session = Process.GetCurrentProcess().SessionId;
        return Array.FindAll(Process.GetProcessesByName("msedge"), process => process.SessionId == session);
    }

    private static bool CloseEdge()
    {
        bool wasOpen = false;
        foreach (var process in RunningEdge())
        {
            using (process)
            {
                if (process.MainWindowHandle != IntPtr.Zero)
                    wasOpen |= process.CloseMainWindow();
            }
        }
        for (int i = 0; i < 25; i++)
        {
            if (RunningEdge().Length == 0)
                return wasOpen;
            Thread.Sleep(100);
        }
        if (StopIdleStartupBoost())
        {
            for (int i = 0; i < 30; i++)
            {
                if (RunningEdge().Length == 0)
                    return wasOpen;
                Thread.Sleep(100);
            }
        }
        throw new InvalidOperationException("Edge 仍在运行。请储存网页工作，从 Edge 菜单选择关闭 Microsoft Edge，再点一次切换。");
    }

    private static bool StopIdleStartupBoost()
    {
        var candidates = RunningEdge();
        try
        {
            // Startup Boost can spawn a new windowless parent after all Edge
            // windows exited normally. Leave any ordinary browser process alone.
            if (Array.Exists(candidates, item => item.MainWindowHandle != IntPtr.Zero))
                return false;
            using (var finder = new ManagementObjectSearcher(
                "SELECT ProcessId, CommandLine, ExecutablePath FROM Win32_Process WHERE Name='msedge.exe'"))
            using (var records = finder.Get())
            {
                foreach (ManagementObject item in records)
                using (item)
                {
                    int id = Convert.ToInt32(item["ProcessId"]);
                    var process = Array.Find(candidates, candidate => candidate.Id == id);
                    var command = item["CommandLine"] as string ?? "";
                    if (process == null || !String.Equals(item["ExecutablePath"] as string,
                        EdgePath, StringComparison.OrdinalIgnoreCase) ||
                        !Regex.IsMatch(command, @"(^|\s)--no-startup-window(\s|$)") ||
                        Regex.IsMatch(command, @"(^|\s)--(type|user-data-dir)="))
                        continue;
                    process.Refresh();
                    if (!process.HasExited && process.MainWindowHandle == IntPtr.Zero)
                    {
                        process.Kill();
                        return true;
                    }
                }
            }
            return false;
        }
        finally
        {
            foreach (var process in candidates)
                process.Dispose();
        }
    }

    private static void Launch(bool american, string locale, string profile)
    {
        // Session restore keeps all ordinary tabs. During US mode, suppress profile
        // synchronization for this launch so its temporary language stays local.
        string arguments = "--restore-last-session --profile-directory=\"" + profile + "\" --disable-features=msEdgeStartupBoost";
        if (american)
            arguments += " --disable-sync --lang=en-US";
        else if (locale == "zh-CN")
            arguments += " --lang=zh-CN";
        using (var browser = Process.Start(new ProcessStartInfo(EdgePath, arguments) { UseShellExecute = false }))
        {
            if (browser == null)
                throw new InvalidOperationException("Edge 没有重新打开。");
        }
    }

    private static Dictionary<string, object> CurrentLanguages(
        Dictionary<string, object> state, Dictionary<string, object> prefs)
    {
        var preferences = GetOrCreateIntl(prefs);
        var browser = GetOrCreateIntl(state);
        return new Dictionary<string, object>
        {
            { "locale", StringValue(browser, "app_locale") },
            { "accept", StringValue(preferences, "accept_languages") },
            { "selected", StringValue(preferences, "selected_languages") }
        };
    }

    private static bool Same(Dictionary<string, object> a, Dictionary<string, object> b)
    {
        return StringValue(a, "locale") == StringValue(b, "locale")
            && StringValue(a, "accept") == StringValue(b, "accept")
            && StringValue(a, "selected") == StringValue(b, "selected");
    }

    private static Dictionary<string, object> GetOrCreateIntl(Dictionary<string, object> parent)
    {
        if (!parent.ContainsKey("intl")) parent["intl"] = new Dictionary<string, object>();
        return Dictionary(parent, "intl");
    }

    private static Dictionary<string, object> Dictionary(Dictionary<string, object> parent, string key)
    {
        object value;
        if (parent.TryGetValue(key, out value) && value is Dictionary<string, object>)
            return (Dictionary<string, object>)value;
        throw new InvalidOperationException("Edge 语言配置格式发生变化。");
    }

    private static string StringValue(Dictionary<string, object> values, string key)
    {
        object value;
        return values.TryGetValue(key, out value) ? value as string : null;
    }

    private static void Set(Dictionary<string, object> values, string key, object value)
    {
        if (value == null) values.Remove(key);
        else values[key] = value;
    }

    private static Dictionary<string, object> Read(string path)
    {
        return Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(path));
    }

    private static void Write(string path, string text)
    {
        string temp = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        string backup = temp + ".before";
        try
        {
            File.WriteAllText(temp, text, new UTF8Encoding(false));
            if (File.Exists(path))
                File.Replace(temp, path, backup);
            else
                File.Move(temp, path);
        }
        finally
        {
            if (File.Exists(temp)) File.Delete(temp);
            if (File.Exists(backup)) File.Delete(backup);
        }
    }
}
