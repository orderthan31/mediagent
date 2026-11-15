// Compile with the Windows .NET Framework compiler: /target:winexe.
// No resident loop, credential changes, shell association, or application control.
using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading.Tasks;

internal static class ResourceObserverLauncher
{
    private static int Finish(int code, int childPid, string detail)
    {
        try
        {
            string text = DateTime.UtcNow.ToString("o") + "\nexit=" + code +
                "\nchild_pid=" + childPid + "\ncreate_no_window=true\n";
            if (!String.IsNullOrEmpty(detail))
                text += detail.Substring(0, Math.Min(detail.Length, 16384));
            File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,
                "last-run.txt"), text, new UTF8Encoding(false));
        }
        catch { /* Task Scheduler still receives the actual exit status. */ }
        return code;
    }

    [STAThread]
    private static int Main(string[] args)
    {
        try
        {
            if (args.Length != 1)
                return Finish(64, 0, "Expected one existing PowerShell script path.");
            string script = Path.GetFullPath(args[0]);
            if (!File.Exists(script) ||
                !String.Equals(Path.GetExtension(script), ".ps1", StringComparison.OrdinalIgnoreCase))
                return Finish(66, 0, "PowerShell script is missing or has an unsupported extension.");
            var start = new ProcessStartInfo
            {
                FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),
                    @"WindowsPowerShell\v1.0\powershell.exe"),
                Arguments = "-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden " +
                    "-ExecutionPolicy Bypass -File \"" + script + "\"",
                WorkingDirectory = Path.GetDirectoryName(script),
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden,
                RedirectStandardOutput = true,
                RedirectStandardError = true
            };
            using (var process = Process.Start(start))
            {
                Task<string> output = process.StandardOutput.ReadToEndAsync();
                Task<string> errors = process.StandardError.ReadToEndAsync();
                process.WaitForExit();
                Task.WaitAll(output, errors);
                return Finish(process.ExitCode, process.Id, errors.Result);
            }
        }
        catch (Exception error)
        {
            // Suppress GUI exception dialogs; preserve bounded local diagnostics.
            return Finish(1, 0, error.GetType().Name + ": " + error.Message);
        }
    }
}
