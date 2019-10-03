from __future__ import print_function

import sys

import click
import six

from dagster import DagsterInvariantViolationError, check
from dagster.cli.load_handle import handle_for_repo_cli_args
from dagster.core.instance import DagsterInstance
from dagster.core.scheduler import ScheduleStatus
from dagster.utils import DEFAULT_REPOSITORY_YAML_FILENAME


def create_schedule_cli_group():
    group = click.Group(name="schedule")
    group.add_command(schedule_list_command)
    group.add_command(schedule_up_command)
    group.add_command(schedule_preview_command)
    group.add_command(schedule_start_command)
    group.add_command(schedule_stop_command)
    return group


# With the SystemCronScheduler, we currently only target a repository.yaml file since we need
# an absolute path to the repository that we can use in the cron job bash script. When using
# the combination of --python-file --fn-name flags, ExecutionTargetHandle doesn't contain an
# absolute path to the python file, but we can eventually change that to support these flags.
REPO_TARGET_WARNING = 'Can only use --repository-yaml/-y'


def apply_click_params(command, *click_params):
    for click_param in click_params:
        command = click_param(command)
    return command


def repository_target_argument(f):
    return apply_click_params(
        f,
        click.option(
            '--repository-yaml',
            '-y',
            type=click.Path(exists=True),
            help=('Path to config file. Defaults to ./{default_filename} not specified').format(
                default_filename=DEFAULT_REPOSITORY_YAML_FILENAME
            ),
        ),
    )


def print_changes(scheduler_handle, print_fn=print):
    changeset = scheduler_handle.get_change_set()
    if len(changeset) == 0:
        print_fn(click.style('No changes to schedules.', fg='magenta', bold=True))
        print_fn('{num} schedules unchanged'.format(num=len(scheduler_handle.all_schedule_defs())))
        return

    print_fn(click.style('Changes:', fg='magenta', bold=True))

    for change in changeset:
        change_type, schedule_name, changes = change

        if change_type == "add":
            print_fn(click.style('  + %s (add)' % schedule_name, fg='green'))

        if change_type == "change":
            print_fn(click.style('  ~ %s (update)' % schedule_name, fg='yellow'))
            for change_name, diff in changes:
                if len(diff) == 2:
                    old, new = diff
                    print_fn(
                        click.style('\t %s: ' % change_name, fg='yellow')
                        + click.style(old, fg='red')
                        + " => "
                        + click.style(new, fg='green')
                    )
                else:
                    print_fn(
                        click.style('\t %s: ' % change_name, fg='yellow')
                        + click.style(diff, fg='green')
                    )

        if change_type == "remove":
            print_fn(click.style('  - %s (delete)' % schedule_name, fg='red'))


@click.command(
    name='preview',
    help='[Experimental] Preview changes that will be performed by `dagster schedule up',
)
@repository_target_argument
def schedule_preview_command(**kwargs):
    return execute_preview_command(kwargs, click.echo)


def execute_preview_command(cli_args, print_fn):
    handle = handle_for_repo_cli_args(cli_args)
    repository = handle.build_repository_definition()

    instance = DagsterInstance.get()
    scheduler_handle = handle.build_scheduler_handle(artifacts_dir=instance.schedules_directory())
    if not scheduler_handle:
        print_fn("Scheduler not defined for repository {name}".format(name=repository.name))
        return

    print_changes(scheduler_handle, print_fn)


@click.command(
    name='up',
    help='[Experimental] Updates the internal dagster representation of schedules to match the list '
    'of ScheduleDefinitions defined in the repository. Use `dagster schedule up --preview` or '
    '`dagster schedule preview` to preview what changes will be applied. New ScheduleDefinitions '
    'will not start running by default when `up` is called. Use `dagster schedule start` and '
    '`dagster schedule stop` to start and stop a schedule. If a ScheduleDefinition is deleted, the '
    'corresponding running schedule will be stopped and deleted.',
)
@click.option('--preview', help="Preview changes", is_flag=True, default=False)
@repository_target_argument
def schedule_up_command(preview, **kwargs):
    return execute_up_command(preview, kwargs, click.echo)


def execute_up_command(preview, cli_args, print_fn):
    handle = handle_for_repo_cli_args(cli_args)
    repository = handle.build_repository_definition()

    python_path = sys.executable
    repository_path = handle.data.repository_yaml

    instance = DagsterInstance.get()
    scheduler_handle = handle.build_scheduler_handle(artifacts_dir=instance.schedules_directory())
    if not scheduler_handle:
        print_fn("Scheduler not defined for repository {name}".format(name=repository.name))
        return

    if preview:
        print_changes(scheduler_handle, print_fn)
        return

    try:
        scheduler_handle.up(python_path, repository_path)
    except DagsterInvariantViolationError as ex:
        raise click.UsageError(ex)


@click.command(
    name='list',
    help="[Experimental] List all schedules that correspond to a repository. {warning}".format(
        warning=REPO_TARGET_WARNING
    ),
)
@repository_target_argument
@click.option('--running', help="Filter for running schedules", is_flag=True, default=False)
@click.option('--stopped', help="Filter for stopped schedules", is_flag=True, default=False)
@click.option('--name', help="Only display schedule schedule names", is_flag=True, default=False)
@click.option('--verbose', is_flag=True)
def schedule_list_command(running, stopped, name, verbose, **kwargs):
    return execute_list_command(running, stopped, name, verbose, kwargs, click.echo)


def execute_list_command(running_filter, stopped_filter, name_filter, verbose, cli_args, print_fn):
    handle = handle_for_repo_cli_args(cli_args)
    repository = handle.build_repository_definition()

    instance = DagsterInstance.get()
    schedule_handle = handle.build_scheduler_handle(artifacts_dir=instance.schedules_directory())

    if not schedule_handle and not name_filter:
        print_fn("Scheduler not defined for repository {name}".format(name=repository.name))
        return

    scheduler = schedule_handle.get_scheduler()

    if not name_filter:
        title = 'Repository {name}'.format(name=repository.name)
        print_fn(title)
        print_fn('*' * len(title))

    first = True

    if running_filter:
        schedules = scheduler.all_schedules(status=ScheduleStatus.RUNNING)
    elif stopped_filter:
        schedules = scheduler.all_schedules(status=ScheduleStatus.STOPPED)
    else:
        schedules = scheduler.all_schedules()

    for schedule in schedules:
        schedule_def = schedule_handle.get_schedule_def_by_name(schedule.name)

        # If --name filter is present, only print the schedule name
        if name_filter:
            print_fn(schedule_def.name)
            continue

        flag = "[{status}]".format(status=schedule.status.value) if schedule else ""
        schedule_title = 'Schedule: {name} {flag}'.format(name=schedule_def.name, flag=flag)

        if not first:
            print_fn('*' * len(schedule_title))
        first = False

        print_fn(schedule_title)
        print_fn('Cron Schedule: {cron_schedule}'.format(cron_schedule=schedule_def.cron_schedule))

        if verbose:
            print_fn(
                'Execution Params: {execution_params}'.format(
                    execution_params=schedule_def.execution_params
                )
            )


def extract_schedule_name(schedule_name):
    if schedule_name and not isinstance(schedule_name, six.string_types):
        if len(schedule_name) == 1:
            return schedule_name[0]
        else:
            check.failed(
                'Can only handle zero or one schedule args. Got {schedule_name}'.format(
                    schedule_name=repr(schedule_name)
                )
            )


@click.command(name='start', help="[Experimental] Start an existing schedule")
@click.argument('schedule_name', nargs=-1)
@click.option('--start-all', help="start all schedules", is_flag=True, default=False)
@repository_target_argument
def schedule_start_command(schedule_name, start_all, **kwargs):
    schedule_name = extract_schedule_name(schedule_name)
    return execute_start_command(schedule_name, start_all, kwargs, click.echo)


def execute_start_command(schedule_name, all_flag, cli_args, print_fn):
    handle = handle_for_repo_cli_args(cli_args)
    repository = handle.build_repository_definition()

    instance = DagsterInstance.get()
    schedule_handle = handle.build_scheduler_handle(artifacts_dir=instance.schedules_directory())

    if not schedule_handle:
        print_fn("Scheduler not defined for repository {name}".format(name=repository.name))
        return

    scheduler = schedule_handle.get_scheduler()
    if all_flag:
        for schedule in scheduler.all_schedules:
            try:
                schedule = scheduler.start_schedule(schedule.name)
            except DagsterInvariantViolationError as ex:
                continue

            print_fn("Started all schedules for repository {name}".format(name=repository.name))
    else:
        try:
            schedule = scheduler.start_schedule(schedule_name)
        except DagsterInvariantViolationError as ex:
            raise click.UsageError(ex)

        print_fn(
            "Started schedule {schedule_name} with ID {schedule_id}".format(
                schedule_name=schedule_name, schedule_id=schedule.schedule_id
            )
        )


@click.command(name='stop', help="[Experimental] Stop an existing schedule")
@click.argument('schedule_name', nargs=-1)
@repository_target_argument
def schedule_stop_command(schedule_name, **kwargs):
    schedule_name = extract_schedule_name(schedule_name)
    return execute_stop_command(schedule_name, kwargs, click.echo)


def execute_stop_command(schedule_name, cli_args, print_fn):
    handle = handle_for_repo_cli_args(cli_args)
    repository = handle.build_repository_definition()

    instance = DagsterInstance.get()
    schedule_handle = handle.build_scheduler_handle(artifacts_dir=instance.schedules_directory())

    if not schedule_handle:
        print_fn("Scheduler not defined for repository {name}".format(name=repository.name))
        return

    scheduler = schedule_handle.get_scheduler()

    try:
        schedule = scheduler.stop_schedule(schedule_name)
    except DagsterInvariantViolationError as ex:
        raise click.UsageError(ex)

    print_fn(
        "Stopped schedule {schedule_name} with ID {schedule_id}".format(
            schedule_name=schedule_name, schedule_id=schedule.schedule_id
        )
    )
