$ErrorActionPreference = 'Stop'
$utf8 = [System.Text.UTF8Encoding]::new($false)
$inputStream = [System.IO.StreamReader]::new([Console]::OpenStandardInput(), $utf8)
$outputStream = [System.IO.StreamWriter]::new([Console]::OpenStandardOutput(), $utf8)
$outputStream.AutoFlush = $true

function Get-LiteralWord($element, $scriptRoot) {
    if ($element -is [System.Management.Automation.Language.StringConstantExpressionAst]) {
        return $element.Value
    }
    if ($element -is [System.Management.Automation.Language.ConstantExpressionAst]) {
        return [string]$element.Value
    }
    if ($element -is [System.Management.Automation.Language.ExpandableStringExpressionAst]) {
        foreach ($nested in $element.NestedExpressions) {
            if ($nested -isnot [System.Management.Automation.Language.VariableExpressionAst] -or $nested.VariablePath.UserPath -ne 'PSScriptRoot') {
                return $null
            }
            if ([string]::IsNullOrEmpty($scriptRoot)) {
                return $null
            }
        }
        return [regex]::Replace($element.Value, '(?i)\$\{?PSScriptRoot\}?', [System.Text.RegularExpressions.MatchEvaluator]{ param($match) $scriptRoot })
    }
    if ($element -is [System.Management.Automation.Language.CommandParameterAst]) {
        return '-' + $element.ParameterName
    }
    return $null
}

while ($null -ne ($line = $inputStream.ReadLine())) {
    $request = $line | ConvertFrom-Json
    $tokens = $null
    $parseErrors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseInput($request.source, [ref]$tokens, [ref]$parseErrors)
    $commands = [System.Collections.Generic.List[object]]::new()
    foreach ($command in $ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.CommandAst] }, $true)) {
        $words = [System.Collections.Generic.List[object]]::new()
        foreach ($element in $command.CommandElements) {
            $words.Add((Get-LiteralWord $element $request.script_root))
            if ($element -is [System.Management.Automation.Language.CommandParameterAst] -and $null -ne $element.Argument) {
                $words.Add((Get-LiteralWord $element.Argument $request.script_root))
            }
        }
        $commands.Add(@{ words = $words.ToArray(); source = $command.Extent.Text })
    }
    $response = @{ commands = $commands.ToArray(); errors = @($parseErrors | ForEach-Object { $_.Message }) }
    $outputStream.WriteLine(($response | ConvertTo-Json -Depth 8 -Compress))
}
