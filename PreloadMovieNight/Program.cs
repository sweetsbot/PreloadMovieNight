// See https://aka.ms/new-console-template for more information

using System.Net;
using System.Net.Http.Json;
using System.Text.Json.Serialization;
using System.Text.Json.Serialization.Metadata;
using Microsoft.Extensions.Configuration;
using Spectre.Console;
using System.CommandLine;
using System.Runtime.CompilerServices;

try
{

    RootCommand rootCommand = new("Precache Remote Source Tool");
    var optionalArgument = new Argument<string>("configFile")
    {
        Description = "Your source configuration. Default precache-settings.ini",
        DefaultValueFactory = (a) => "precache-settings.ini",
    };
    rootCommand.Add(optionalArgument);
    var parseResult = rootCommand.Parse(args);


    var settingsIni = parseResult.GetValue(optionalArgument)!;
    var configuration = new ConfigurationBuilder()
        .SetBasePath(AppDomain.CurrentDomain.BaseDirectory)
        .AddIniFile(settingsIni, optional: false)
        .Build();

    var downloadServerString = GetPath(configuration, "Application:DownloadServer");
    var playlist = configuration["Application:Playlist"] ?? string.Empty;
    if (string.IsNullOrWhiteSpace(playlist))
    {
        AnsiConsole.MarkupLineInterpolated($"[red]ERROR:[/] Playlist is not optional in an Configuration .ini!");
        PromptForClose();
        return 1;
    }

    var downloadServerUrl = new Uri(downloadServerString);
    var downloadBuilder = new Uri(downloadServerUrl, playlist);
    var precacheDirectory = configuration["Application:DownloadDirectory"] ?? string.Empty;
    var fullPrecacheDirectory = Path.GetFullPath(precacheDirectory);
    if (!Directory.Exists(fullPrecacheDirectory))
    {
        AnsiConsole.MarkupLineInterpolated($"[red]ERROR:[/] Cannot find the '{precacheDirectory}' directory.");
        PromptForClose();
        return 1;
    }

    var httpClient = new HttpClient();
    var playlistPath = playlist.StartsWith("http", StringComparison.OrdinalIgnoreCase) ? playlist : downloadBuilder.ToString();
    var response = await httpClient.GetAsync(playlistPath);
    if (response.StatusCode != HttpStatusCode.OK)
    {
        AnsiConsole.MarkupLineInterpolated($"[red]ERROR:[/] Unable to find the file at [yellow]{playlistPath}[/]. Unable to continue.");
        PromptForClose();
        return 1;
    }

    var filenames = await response.Content.ReadFromJsonAsync(AppJsonContext.Default.StringArray) ?? [];
    var totalFileNames = filenames.Length;
    var count = 0;
    foreach (var filename in filenames)
    {
        downloadBuilder = new Uri(downloadServerUrl, filename);

        var fileUri = downloadBuilder.ToString();
        if (filename.StartsWith("http", StringComparison.OrdinalIgnoreCase))
        {
            fileUri = filename;
        }

        var basename = Path.GetFileName(filename);
        var filePath = Path.Combine(fullPrecacheDirectory, basename);
        // if (string.IsNullOrEmpty())
        AnsiConsole.MarkupInterpolated($"Downloading '{basename}'.");
        response = await httpClient.GetAsync(fileUri);
        if (response.StatusCode != HttpStatusCode.OK)
        {
            AnsiConsole.MarkupLineInterpolated($" [red]ERROR:[/] Failed to download file.");
            if (File.Exists(filePath))
            {
                AnsiConsole.MarkupLineInterpolated($" [green]Notice:[/] Deleting previous pre-cached file \"{filename}\".");
                File.Delete(filePath);
            }
            continue;
        }

        await using var stream = response.Content.ReadAsStream();
        await using var outStream = new FileStream(filePath, FileMode.Create,
            FileAccess.Write, FileShare.None);
        try
        {
            await stream.CopyToAsync(outStream);
        }
        catch
        {
            if (File.Exists(filePath))
            {
                AnsiConsole.MarkupLineInterpolated($" [green]Notice:[/] Deleting failed file \"{filename}\".");
                File.Delete(filePath);
            }
        }

        AnsiConsole.MarkupLineInterpolated($" [green]Complete.[/]");
        count += 1;
    }

    AnsiConsole.MarkupLineInterpolated($"[green]Successfully download {count} of {totalFileNames} into cache.[/]");
    PromptForClose();
    return 0;
}
catch (Exception ex)
{
    System.Diagnostics.Debug.WriteLine($"exception of type: '{ex.GetType()}'.");
    AnsiConsole.MarkupLineInterpolated($"[red]ERROR:[/] Failed to precache items. {ex.Message}");
    AnsiConsole.MarkupLineInterpolated($"[red]ERROR:[/] Ensure your plugin is installed and running from the Application Installation Directory.");
    PromptForClose();
    return 1;
}

void PromptForClose()
{
    Console.WriteLine("Press enter to exit.");
    Console.ReadLine();
}
string GetPath(IConfiguration config, string location)
{
    var f = config[location];

    if (!string.IsNullOrEmpty(f) && !f.EndsWith('/'))
    {
        return f + '/';
    }

    return f ?? "";
}

[JsonSerializable(typeof(string[]))]
internal partial class AppJsonContext : JsonSerializerContext
{
}