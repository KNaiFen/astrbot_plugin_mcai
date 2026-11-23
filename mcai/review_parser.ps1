using namespace System.Management.Automation.Language

$ErrorActionPreference = 'Stop'
$utf8 = [System.Text.UTF8Encoding]::new($false)
$inputStream = [System.IO.StreamReader]::new([Console]::OpenStandardInput(), $utf8)
$outputStream = [System.IO.StreamWriter]::new([Console]::OpenStandardOutput(), $utf8)
$outputStream.AutoFlush = $true

function Get-ConstantString($element, $scriptRoot, $locals) {
    if ($element -is [StringConstantExpressionAst]) {
        return $element.Value
    }
    if ($element -is [VariableExpressionAst] -and $element.VariablePath.IsUnqualified -and -not $element.Splatted) {
        $name = $element.VariablePath.UserPath
        if ($name -eq 'PSScriptRoot') {
            return $scriptRoot
        }
        $binding = $locals[$name]
        if ($null -ne $binding -and $binding.End -le $element.Extent.StartOffset) {
            return $binding.Value
        }
    }
    if ($element -is [BinaryExpressionAst] -and $element.Operator -eq 'Plus') {
        $left = Get-ConstantString $element.Left $scriptRoot $locals
        $right = Get-ConstantString $element.Right $scriptRoot $locals
        if ($null -ne $left -and $null -ne $right -and $left.Length + $right.Length -le 32767) {
            return $left + $right
        }
    }
    if ($element -is [ParenExpressionAst] -and $element.Pipeline -is [PipelineAst] -and $element.Pipeline.PipelineElements.Count -eq 1) {
        $inner = $element.Pipeline.PipelineElements[0]
        if ($inner -is [CommandExpressionAst] -and $inner.Redirections.Count -eq 0) {
            return Get-ConstantString $inner.Expression $scriptRoot $locals
        }
    }
    if ($element -is [ExpandableStringExpressionAst]) {
        # Replace only AST variable spans; do not try to decode escapes.
        $text = $element.Extent.Text
        $quoted = $text -match '^"[^"“”„‟]*"$'
        $bare = $element.StringConstantType -eq 'BareWord' -and $text -notmatch '["''“”‘’„‟]'
        if ($text.Length -gt 32769 -or -not ($quoted -or $bare) -or $text.Contains([char]96)) {
            return $null
        }
        for ($i = $element.NestedExpressions.Count - 1; $i -ge 0; $i--) {
            $nested = $element.NestedExpressions[$i]
            if ($nested -isnot [VariableExpressionAst]) { return $null }
            $value = Get-ConstantString $nested $scriptRoot $locals
            if ($null -eq $value) {
                return $null
            }
            $start = $nested.Extent.StartOffset - $element.Extent.StartOffset
            $length = $nested.Extent.EndOffset - $nested.Extent.StartOffset
            if ($text.Length - $length + $value.Length -gt 32769) { return $null }
            $text = $text.Remove($start, $length).Insert($start, $value)
        }
        if ($quoted) { return $text.Substring(1, $text.Length - 2) }
        return $text
    }
    return $null
}

function Get-LiteralWord($element, $scriptRoot, $locals) {
    if ($element -is [CommandParameterAst]) {
        return '-' + $element.ParameterName
    }
    if ($element -is [ConstantExpressionAst] -and $element -isnot [StringConstantExpressionAst]) {
        return [string]$element.Value
    }
    return Get-ConstantString $element $scriptRoot $locals
}

function Get-AssignmentString($rhs, $scriptRoot, $locals, $joinPathAvailable) {
    if ($rhs -is [CommandExpressionAst] -and $rhs.Redirections.Count -eq 0) {
        return Get-ConstantString $rhs.Expression $scriptRoot $locals
    }
    if ($rhs -isnot [PipelineAst] -or $rhs.PipelineElements.Count -ne 1) {
        return $null
    }
    $call = $rhs.PipelineElements[0]
    if ($call -is [CommandExpressionAst] -and $call.Redirections.Count -eq 0) {
        return Get-ConstantString $call.Expression $scriptRoot $locals
    }
    if (-not $joinPathAvailable -or $call -isnot [CommandAst] -or $call.InvocationOperator -ne 'Unknown' -or
        $call.Redirections.Count -ne 0 -or $call.GetCommandName() -notin @('Join-Path', 'Microsoft.PowerShell.Management\Join-Path')) {
        return $null
    }
    $paths = @{}
    $positional = [System.Collections.Generic.Queue[string]]::new()
    for ($i = 1; $i -lt $call.CommandElements.Count; $i++) {
        $argument = $call.CommandElements[$i]
        if ($argument -is [CommandParameterAst]) {
            $name = $argument.ParameterName
            if ($name -notin @('Path', 'ChildPath') -or $paths.ContainsKey($name)) { return $null }
            $argument = $argument.Argument
            if ($null -eq $argument) {
                if (++$i -ge $call.CommandElements.Count) { return $null }
                $argument = $call.CommandElements[$i]
            }
            $paths[$name] = Get-ConstantString $argument $scriptRoot $locals
        } else {
            $positional.Enqueue((Get-ConstantString $argument $scriptRoot $locals))
        }
    }
    foreach ($name in @('Path', 'ChildPath')) {
        if (-not $paths.ContainsKey($name) -and $positional.Count) {
            $paths[$name] = $positional.Dequeue()
        }
    }
    $parent, $child = $paths.Path, $paths.ChildPath
    # Only ordinary filesystem paths, joined lexically without a provider lookup.
    if ($positional.Count -or -not $parent -or -not $child -or $parent -match '[*?\[\]]' -or
        ($parent -match ':' -and $parent -notmatch '^[A-Za-z]:[\\/][^:]*$') -or
        $child -match '^[\\/]|[:*?\[\]]' -or $parent.Length + $child.Length -ge 32767) {
        return $null
    }
    return $parent.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar + $child
}

while ($null -ne ($line = $inputStream.ReadLine())) {
    $request = $line | ConvertFrom-Json
    $tokens = $null
    $parseErrors = $null
    $ast = [Parser]::ParseInput($request.source, [ref]$tokens, [ref]$parseErrors)
    $writes = @{}
    $joinPathAvailable = $true
    $directWritesOnly = $true
    $nodes = $ast.FindAll({
        param($node)
        $node -is [AssignmentStatementAst] -or $node -is [ParameterAst] -or $node -is [ForEachStatementAst] -or
        $node -is [UnaryExpressionAst] -or $node -is [ConvertExpressionAst] -or
        $node -is [FunctionDefinitionAst] -or $node -is [CommandAst]
    }, $true)
    foreach ($node in $nodes) {
        $target = $null
        if ($node -is [AssignmentStatementAst]) { $target = $node.Left }
        elseif ($node -is [ParameterAst]) { $target = $node.Name }
        elseif ($node -is [ForEachStatementAst]) { $target = $node.Variable }
        elseif ($node -is [UnaryExpressionAst] -and $node.TokenKind -in @('PlusPlus', 'MinusMinus', 'PostfixPlusPlus', 'PostfixMinusMinus')) {
            $target = $node.Child
        } elseif ($node -is [ConvertExpressionAst] -and $node.Type.TypeName.FullName -in @('ref', 'PSReference', 'System.Management.Automation.PSReference')) {
            $target = $node.Child
        } elseif ($node -is [FunctionDefinitionAst] -and ($node.Name -split ':')[-1] -eq 'Join-Path') {
            $joinPathAvailable = $false
        } elseif ($node -is [CommandAst]) {
            $name = ($node.GetCommandName() -split '\\')[-1]
            if ($name -in @('Set-Alias', 'New-Alias', 'Import-Module', 'sal', 'nal', 'ipmo')) {
                $joinPathAvailable = $false
            }
            if ($name -in @('Set-Variable', 'New-Variable', 'Clear-Variable', 'Remove-Variable', 'sv', 'nv', 'clv', 'rv')) {
                $directWritesOnly = $false
            }
            foreach ($element in $node.CommandElements) {
                if ($element -is [CommandParameterAst] -and $element.ParameterName -in @('OutVariable', 'ov', 'PipelineVariable', 'pv', 'ErrorVariable', 'ev', 'WarningVariable', 'wv', 'InformationVariable', 'iv')) {
                    $directWritesOnly = $false
                }
            }
        }
        if ($null -ne $target) {
            foreach ($variable in $target.FindAll({ param($item) $item -is [VariableExpressionAst] }, $true)) {
                if ($variable.VariablePath.IsVariable) {
                    $name = ($variable.VariablePath.UserPath -split ':')[-1]
                    $writes[$name]++
                }
            }
        }
    }

    $scriptRoot = $request.script_root
    if (-not $directWritesOnly -or $writes.ContainsKey('PSScriptRoot')) { $scriptRoot = $null }
    $locals = @{}
    # Only straight-line assignments in the implicit script body. Count writes
    # in all nested scopes before allowing any use, even an earlier one.
    if ($directWritesOnly -and $ast.EndBlock.Unnamed -and $ast.EndBlock.Traps.Count -eq 0) {
        foreach ($statement in $ast.EndBlock.Statements) {
            if ($statement -isnot [AssignmentStatementAst] -or $statement.Operator -ne 'Equals' -or
                $statement.Left -isnot [VariableExpressionAst] -or -not $statement.Left.VariablePath.IsUnqualified) {
                continue
            }
            $name = $statement.Left.VariablePath.UserPath
            if ($writes[$name] -ne 1 -or $name -in @('PSScriptRoot', 'PSCommandPath', 'args', 'input', '_', 'PSItem', 'this', 'PSBoundParameters')) {
                continue
            }
            $value = Get-AssignmentString $statement.Right $scriptRoot $locals $joinPathAvailable
            if ($null -ne $value) {
                $locals[$name] = @{ Value = $value; End = $statement.Extent.EndOffset }
            }
        }
    }
    $commands = [System.Collections.Generic.List[object]]::new()
    foreach ($command in $nodes) {
        if ($command -isnot [CommandAst]) { continue }
        $bindings = @{}
        $pipeline = $command.Parent
        $statementParent = $pipeline.Parent
        if ($statementParent -is [AssignmentStatementAst]) { $statementParent = $statementParent.Parent }
        if ($pipeline -is [PipelineAst] -and $statementParent -eq $ast.EndBlock -and $pipeline.PipelineElements[0] -eq $command) {
            $bindings = $locals
        }
        $words = [System.Collections.Generic.List[object]]::new()
        foreach ($element in $command.CommandElements) {
            $words.Add((Get-LiteralWord $element $scriptRoot $bindings))
            if ($element -is [CommandParameterAst] -and $null -ne $element.Argument) {
                $words.Add((Get-LiteralWord $element.Argument $scriptRoot $bindings))
            }
        }
        $commands.Add(@{ words = $words.ToArray(); source = $command.Extent.Text })
    }
    foreach ($member in $ast.FindAll({ param($node) $node -is [InvokeMemberExpressionAst] }, $true)) {
        $method = $member.Member.Value
        if ($method -in @('Create', 'InvokeScript') -and $member.Extent.Text -match '(?i)(scriptblock|InvokeCommand|ExecutionContext)') {
            $commands.Add(@{ words = @('__unsafe_ast__', $method); source = $member.Extent.Text })
        }
    }
    $response = @{ commands = $commands.ToArray(); errors = @($parseErrors | ForEach-Object { $_.Message }) }
    $outputStream.WriteLine(($response | ConvertTo-Json -Depth 8 -Compress))
}
